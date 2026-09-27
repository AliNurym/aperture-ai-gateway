use anchor_lang::prelude::*;
use anchor_lang::system_program;
use std::str::FromStr;

declare_id!("A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ");

pub const PROTOCOL_VERSION: u16 = 2;
pub const MAX_BURN_RATE_LAMPORTS_PER_SECOND: u64 = 25_000;
pub const MAX_TASK_RUNTIME_SECONDS: u32 = 3_600;

fn configured_protocol_authority() -> Result<Pubkey> {
    let authority_str = option_env!("APERTURE_CONFIG_AUTHORITY")
        .ok_or(ApertureError::ConfigAuthorityNotConfigured)?;
    let authority = Pubkey::from_str(authority_str)
        .map_err(|_| error!(ApertureError::ConfigAuthorityNotConfigured))?;
    require!(
        authority != Pubkey::default() && authority != system_program::ID && authority != crate::ID,
        ApertureError::ConfigAuthorityNotConfigured
    );
    Ok(authority)
}

fn require_v2(config: &ProtocolConfig) -> Result<()> {
    require!(
        config.version == PROTOCOL_VERSION,
        ApertureError::InvalidVersion
    );
    Ok(())
}

fn validate_policy(
    max_cost: u64,
    max_runtime: u32,
    valid_until: i64,
    total_budget: u64,
    spent: u64,
    now: i64,
) -> Result<()> {
    require!(
        max_cost > 0 && total_budget >= max_cost,
        ApertureError::InvalidPolicy
    );
    require!(spent <= total_budget, ApertureError::AllowanceExceeded);
    require!(
        max_runtime > 0 && max_runtime <= MAX_TASK_RUNTIME_SECONDS,
        ApertureError::InvalidRuntime
    );
    require!(valid_until > now, ApertureError::PassportExpired);
    Ok(())
}

fn apply_policy(
    passport: &mut AgentPassport,
    metadata_hash: [u8; 32],
    max_cost: u64,
    max_runtime: u32,
    valid_until: i64,
    total_budget: u64,
    now: i64,
) -> Result<()> {
    require!(passport.reserved == 0, ApertureError::PassportBusy);
    require!(metadata_hash != [0; 32], ApertureError::InvalidHash);
    validate_policy(
        max_cost,
        max_runtime,
        valid_until,
        total_budget,
        passport.spent,
        now,
    )?;
    passport.metadata_hash = metadata_hash;
    passport.max_cost = max_cost;
    passport.max_runtime = max_runtime;
    passport.valid_until = valid_until;
    passport.total_budget = total_budget;
    // Changing a policy cannot replenish already consumed allowance.
    passport.revoked = false;
    passport.revoked_at = 0;
    Ok(())
}

fn validate_passport_identity(
    passport_key: Pubkey,
    passport: &AgentPassport,
    owner: Pubkey,
    agent: Pubkey,
) -> Result<()> {
    let (expected_key, expected_bump) =
        Pubkey::find_program_address(&[b"agent", agent.as_ref()], &crate::ID);
    require_keys_eq!(passport_key, expected_key, ApertureError::InvalidPassport);
    require!(
        passport.bump == expected_bump,
        ApertureError::InvalidPassport
    );
    require_keys_eq!(passport.owner, owner, ApertureError::UnauthorizedOwner);
    require_keys_eq!(passport.agent, agent, ApertureError::InvalidAgent);
    Ok(())
}

fn reserve_allowance(
    passport: &mut AgentPassport,
    owner: Pubkey,
    agent: Pubkey,
    max_cost: u64,
    max_runtime: u32,
    now: i64,
) -> Result<i64> {
    require_keys_eq!(passport.owner, owner, ApertureError::UnauthorizedOwner);
    require_keys_eq!(passport.agent, agent, ApertureError::InvalidAgent);
    require!(!passport.revoked, ApertureError::PassportRevoked);
    require!(passport.valid_until > now, ApertureError::PassportExpired);
    require!(
        max_cost <= passport.max_cost,
        ApertureError::AllowanceExceeded
    );
    require!(
        max_runtime <= passport.max_runtime,
        ApertureError::InvalidRuntime
    );
    let reserved = passport
        .reserved
        .checked_add(max_cost)
        .ok_or(ApertureError::MathOverflow)?;
    let committed = passport
        .spent
        .checked_add(reserved)
        .ok_or(ApertureError::MathOverflow)?;
    require!(
        committed <= passport.total_budget,
        ApertureError::AllowanceExceeded
    );
    let deadline = now
        .checked_add(i64::from(max_runtime))
        .ok_or(ApertureError::MathOverflow)?;
    passport.reserved = reserved;
    Ok(deadline.min(passport.valid_until))
}

fn revoke_passport(passport: &mut AgentPassport, now: i64) {
    // Repeated revoke must not move the cutoff later and increase a charge.
    if !passport.revoked {
        passport.revoked = true;
        passport.revoked_at = now;
    }
}

fn bounded_charge(
    balance: u64,
    rate: u64,
    max_cost: u64,
    started_at: i64,
    deadline: i64,
    now: i64,
    revoked_at: Option<i64>,
) -> u64 {
    let cutoff = now.min(deadline).min(revoked_at.unwrap_or(i64::MAX));
    // Widen before subtracting and multiplying. Clock rollback means zero elapsed time.
    let elapsed = (i128::from(cutoff) - i128::from(started_at)).max(0) as u128;
    (elapsed * u128::from(rate))
        .min(u128::from(max_cost))
        .min(u128::from(balance)) as u64
}

fn settle_task_state(
    channel: &mut ChannelState,
    passport: Option<&mut AgentPassport>,
    receipt: &mut TaskReceipt,
    task_hash: [u8; 32],
    now: i64,
) -> Result<Option<u64>> {
    require!(receipt.task_hash == task_hash, ApertureError::TaskMismatch);
    require_keys_eq!(
        receipt.owner,
        channel.user,
        ApertureError::UnauthorizedOwner
    );
    // A retry for an old settled task cannot alter a newer channel task.
    if receipt.settled {
        return Ok(None);
    }
    require!(
        channel.task_hash == task_hash && channel.burn_rate > 0,
        ApertureError::TaskMismatch
    );
    require_keys_eq!(receipt.agent, channel.agent, ApertureError::InvalidAgent);
    require!(
        receipt.rate == channel.burn_rate
            && receipt.max_cost == channel.task_max_cost
            && receipt.started_at == channel.task_started_at
            && receipt.deadline == channel.task_deadline,
        ApertureError::TaskMismatch
    );
    let delegated = channel.agent != channel.user;
    require!(
        delegated == passport.is_some(),
        ApertureError::InvalidPassport
    );
    let revoked_at = passport
        .as_ref()
        .and_then(|p| p.revoked.then_some(p.revoked_at));
    let charge = bounded_charge(
        channel.balance,
        receipt.rate,
        receipt.max_cost,
        receipt.started_at,
        receipt.deadline,
        now,
        revoked_at,
    );
    // Validate all accounting before mutating, including for pure state callers/tests.
    let new_passport_state = if let Some(p) = passport.as_ref() {
        require_keys_eq!(p.owner, channel.user, ApertureError::UnauthorizedOwner);
        require_keys_eq!(p.agent, channel.agent, ApertureError::InvalidAgent);
        let reserved = p
            .reserved
            .checked_sub(receipt.max_cost)
            .ok_or(ApertureError::InvalidReservation)?;
        let spent = p
            .spent
            .checked_add(charge)
            .ok_or(ApertureError::MathOverflow)?;
        require!(spent <= p.total_budget, ApertureError::AllowanceExceeded);
        Some((reserved, spent))
    } else {
        None
    };
    if let (Some(p), Some((reserved, spent))) = (passport, new_passport_state) {
        p.reserved = reserved;
        p.spent = spent;
    }
    receipt.charged_lamports = charge;
    receipt.settled_at = now;
    receipt.settled = true;
    channel.balance = channel
        .balance
        .checked_sub(charge)
        .ok_or(ApertureError::MathOverflow)?;
    channel.last_task_hash = task_hash;
    channel.last_charged = charge;
    channel.last_update_time = now;
    channel.burn_rate = 0;
    channel.agent = Pubkey::default();
    channel.task_hash = [0; 32];
    channel.task_max_cost = 0;
    channel.task_deadline = 0;
    channel.task_started_at = 0;
    Ok(Some(charge))
}

fn pay_from_channel(
    channel: &AccountInfo,
    destination: &AccountInfo,
    amount: u64,
    require_rent_exempt_destination: bool,
) -> Result<()> {
    require!(
        channel.key != destination.key,
        ApertureError::InvalidTreasury
    );
    let remaining = channel
        .lamports()
        .checked_sub(amount)
        .ok_or(ApertureError::InsufficientBalance)?;
    require!(
        remaining >= Rent::get()?.minimum_balance(channel.data_len()),
        ApertureError::InsufficientBalance
    );
    let credited = destination
        .lamports()
        .checked_add(amount)
        .ok_or(ApertureError::MathOverflow)?;
    if amount > 0 && require_rent_exempt_destination {
        require!(
            credited >= Rent::get()?.minimum_balance(destination.data_len()),
            ApertureError::PaymentRecipientNotRentExempt
        );
    }
    if amount > 0 {
        **channel.try_borrow_mut_lamports()? = remaining;
        **destination.try_borrow_mut_lamports()? = credited;
    }
    Ok(())
}

fn require_rent_exempt_payment_destination(destination: &AccountInfo) -> Result<()> {
    require!(
        destination.lamports() >= Rent::get()?.minimum_balance(destination.data_len()),
        ApertureError::PaymentRecipientNotRentExempt
    );
    Ok(())
}

#[program]
pub mod aperture_gateway {
    use super::*;

    pub fn initialize_config(ctx: Context<InitializeConfig>, treasury: Pubkey) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.authority.key(),
            configured_protocol_authority()?,
            ApertureError::UnauthorizedConfigAuthority
        );
        require!(
            treasury != Pubkey::default()
                && treasury != system_program::ID
                && treasury != crate::ID,
            ApertureError::InvalidTreasury
        );
        let config = &mut ctx.accounts.config;
        config.authority = ctx.accounts.authority.key();
        config.oracle = ctx.accounts.authority.key();
        config.treasury = treasury;
        config.bump = ctx.bumps.config;
        config.version = PROTOCOL_VERSION;
        Ok(())
    }

    /// Registers a wallet-owner-issued permission for python.execute tasks.
    pub fn register_agent(
        ctx: Context<RegisterAgent>,
        metadata_hash: [u8; 32],
        max_cost: u64,
        max_runtime: u32,
        valid_until: i64,
        total_budget: u64,
    ) -> Result<()> {
        let agent_key = ctx.accounts.agent.key();
        require!(
            agent_key != ctx.accounts.owner.key()
                && agent_key != Pubkey::default()
                && agent_key != crate::ID,
            ApertureError::InvalidAgent
        );
        let passport = &mut ctx.accounts.passport;
        passport.owner = ctx.accounts.owner.key();
        passport.agent = agent_key;
        passport.bump = ctx.bumps.passport;
        apply_policy(
            passport,
            metadata_hash,
            max_cost,
            max_runtime,
            valid_until,
            total_budget,
            Clock::get()?.unix_timestamp,
        )
    }

    /// Policy changes preserve spent allowance and cannot replace active reservations.
    pub fn update_agent(
        ctx: Context<ManageAgent>,
        metadata_hash: [u8; 32],
        max_cost: u64,
        max_runtime: u32,
        valid_until: i64,
        total_budget: u64,
    ) -> Result<()> {
        apply_policy(
            &mut ctx.accounts.passport,
            metadata_hash,
            max_cost,
            max_runtime,
            valid_until,
            total_budget,
            Clock::get()?.unix_timestamp,
        )
    }

    pub fn revoke_agent(ctx: Context<ManageAgent>) -> Result<()> {
        revoke_passport(&mut ctx.accounts.passport, Clock::get()?.unix_timestamp);
        Ok(())
    }

    pub fn open_channel(ctx: Context<OpenChannel>, initial_deposit: u64) -> Result<()> {
        require_v2(&ctx.accounts.config)?;
        require!(initial_deposit > 0, ApertureError::InsufficientBalance);
        let channel_info = ctx.accounts.channel.to_account_info();
        let channel = &mut ctx.accounts.channel;
        channel.user = ctx.accounts.user.key();
        channel.oracle = ctx.accounts.config.oracle;
        channel.last_update_time = Clock::get()?.unix_timestamp;
        channel.bump = ctx.bumps.channel;
        system_program::transfer(
            CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.user.to_account_info(),
                    to: channel_info.clone(),
                },
            ),
            initial_deposit,
        )?;
        channel.balance = channel_info
            .lamports()
            .checked_sub(Rent::get()?.minimum_balance(channel_info.data_len()))
            .ok_or(ApertureError::InsufficientBalance)?;
        Ok(())
    }

    pub fn top_up(ctx: Context<TopUpChannel>, amount: u64) -> Result<()> {
        require!(
            ctx.accounts.channel.burn_rate == 0,
            ApertureError::ChannelBusy
        );
        require!(amount > 0, ApertureError::InsufficientBalance);
        let balance = ctx
            .accounts
            .channel
            .balance
            .checked_add(amount)
            .ok_or(ApertureError::MathOverflow)?;
        system_program::transfer(
            CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.user.to_account_info(),
                    to: ctx.accounts.channel.to_account_info(),
                },
            ),
            amount,
        )?;
        ctx.accounts.channel.balance = balance;
        Ok(())
    }

    /// The oracle attests gateway-verified quote consent; the contract bounds payment independently.
    pub fn start_task(
        ctx: Context<StartTask>,
        task_hash: [u8; 32],
        source_hash: [u8; 32],
        agent: Pubkey,
        rate: u64,
        max_cost: u64,
        max_runtime: u32,
    ) -> Result<()> {
        require_v2(&ctx.accounts.config)?;
        require_rent_exempt_payment_destination(&ctx.accounts.treasury.to_account_info())?;
        require!(
            ctx.accounts.channel.burn_rate == 0 && ctx.accounts.channel.task_hash == [0; 32],
            ApertureError::ChannelBusy
        );
        require!(
            task_hash != [0; 32] && source_hash != [0; 32],
            ApertureError::InvalidHash
        );
        require!(
            agent != Pubkey::default() && agent != crate::ID,
            ApertureError::InvalidAgent
        );
        require!(
            rate > 0 && rate <= MAX_BURN_RATE_LAMPORTS_PER_SECOND,
            ApertureError::BurnRateTooHigh
        );
        require!(
            max_runtime > 0 && max_runtime <= MAX_TASK_RUNTIME_SECONDS,
            ApertureError::InvalidRuntime
        );
        require!(
            max_cost > 0 && max_cost <= ctx.accounts.channel.balance,
            ApertureError::InsufficientBalance
        );
        let now = Clock::get()?.unix_timestamp;
        let deadline = if agent == ctx.accounts.channel.user {
            require!(
                ctx.accounts.passport.is_none(),
                ApertureError::InvalidPassport
            );
            now.checked_add(i64::from(max_runtime))
                .ok_or(ApertureError::MathOverflow)?
        } else {
            let passport = ctx
                .accounts
                .passport
                .as_mut()
                .ok_or(ApertureError::InvalidPassport)?;
            validate_passport_identity(passport.key(), passport, ctx.accounts.channel.user, agent)?;
            reserve_allowance(
                passport,
                ctx.accounts.channel.user,
                agent,
                max_cost,
                max_runtime,
                now,
            )?
        };
        let receipt = &mut ctx.accounts.receipt;
        receipt.owner = ctx.accounts.channel.user;
        receipt.agent = agent;
        receipt.task_hash = task_hash;
        receipt.source_hash = source_hash;
        receipt.rate = rate;
        receipt.max_cost = max_cost;
        receipt.started_at = now;
        receipt.deadline = deadline;
        receipt.bump = ctx.bumps.receipt;
        let channel = &mut ctx.accounts.channel;
        channel.agent = agent;
        channel.task_hash = task_hash;
        channel.task_max_cost = max_cost;
        channel.task_deadline = deadline;
        channel.task_started_at = now;
        channel.last_update_time = now;
        channel.burn_rate = rate;
        emit!(TaskStartedEvent {
            owner: channel.user,
            agent,
            task_hash,
            max_cost,
            deadline,
            rate
        });
        Ok(())
    }

    pub fn stop_task(ctx: Context<StopTask>, task_hash: [u8; 32]) -> Result<()> {
        require_v2(&ctx.accounts.config)?;
        if !ctx.accounts.receipt.settled {
            if let Some(passport) = ctx.accounts.passport.as_ref() {
                validate_passport_identity(
                    passport.key(),
                    passport,
                    ctx.accounts.channel.user,
                    ctx.accounts.channel.agent,
                )?;
            }
        }
        let now = Clock::get()?.unix_timestamp;
        if let Some(charge) = settle_task_state(
            &mut ctx.accounts.channel,
            ctx.accounts.passport.as_mut().map(|p| &mut **p),
            &mut ctx.accounts.receipt,
            task_hash,
            now,
        )? {
            pay_from_channel(
                &ctx.accounts.channel.to_account_info(),
                &ctx.accounts.treasury.to_account_info(),
                charge,
                true,
            )?;
            emit!(TaskSettledEvent {
                owner: ctx.accounts.receipt.owner,
                agent: ctx.accounts.receipt.agent,
                task_hash,
                charged_lamports: charge,
                settled_at: now
            });
        }
        Ok(())
    }

    /// Keeps legacy clients from starting unbounded accrual. Active tasks require stop_task.
    pub fn update_burn_rate(ctx: Context<UpdateBurnRate>, new_rate: u64) -> Result<()> {
        require_v2(&ctx.accounts.config)?;
        require!(
            new_rate == 0 && ctx.accounts.channel.burn_rate == 0,
            ApertureError::BoundedTaskRequired
        );
        Ok(())
    }

    /// The owner can settle and withdraw even when the oracle is offline.
    pub fn close_channel(ctx: Context<CloseChannel>) -> Result<()> {
        require_v2(&ctx.accounts.config)?;
        if ctx.accounts.channel.burn_rate > 0 {
            let task_hash = ctx.accounts.channel.task_hash;
            let receipt = ctx
                .accounts
                .receipt
                .as_mut()
                .ok_or(ApertureError::MissingReceipt)?;
            let (expected_key, expected_bump) =
                Pubkey::find_program_address(&[b"task", &task_hash], &crate::ID);
            require_keys_eq!(receipt.key(), expected_key, ApertureError::TaskMismatch);
            require!(
                receipt.bump == expected_bump && !receipt.settled,
                ApertureError::TaskMismatch
            );
            if let Some(passport) = ctx.accounts.passport.as_ref() {
                validate_passport_identity(
                    passport.key(),
                    passport,
                    ctx.accounts.channel.user,
                    ctx.accounts.channel.agent,
                )?;
            }
            let now = Clock::get()?.unix_timestamp;
            let charge = settle_task_state(
                &mut ctx.accounts.channel,
                ctx.accounts.passport.as_mut().map(|p| &mut **p),
                receipt,
                task_hash,
                now,
            )?
            .ok_or(ApertureError::TaskMismatch)?;
            pay_from_channel(
                &ctx.accounts.channel.to_account_info(),
                &ctx.accounts.treasury.to_account_info(),
                charge,
                true,
            )?;
            emit!(TaskSettledEvent {
                owner: receipt.owner,
                agent: receipt.agent,
                task_hash,
                charged_lamports: charge,
                settled_at: now
            });
        } else {
            require!(
                ctx.accounts.channel.task_hash == [0; 32],
                ApertureError::TaskMismatch
            );
        }
        let refund = ctx.accounts.channel.balance;
        pay_from_channel(
            &ctx.accounts.channel.to_account_info(),
            &ctx.accounts.user.to_account_info(),
            refund,
            false,
        )?;
        ctx.accounts.channel.balance = 0;
        // Anchor's close constraint refunds rent and any direct donations. Receipt is not closed.
        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeConfig<'info> {
    #[account(init, payer = authority, space = 8 + ProtocolConfig::INIT_SPACE, seeds = [b"config"], bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct RegisterAgent<'info> {
    #[account(init, payer = owner, space = 8 + AgentPassport::INIT_SPACE, seeds = [b"agent", agent.key().as_ref()], bump)]
    pub passport: Account<'info, AgentPassport>,
    #[account(mut)]
    pub owner: Signer<'info>,
    /// CHECK: The owner nominates this public key; possession is checked by the gateway's task signature.
    pub agent: UncheckedAccount<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ManageAgent<'info> {
    #[account(mut, seeds = [b"agent", passport.agent.as_ref()], bump = passport.bump, has_one = owner @ ApertureError::UnauthorizedOwner)]
    pub passport: Account<'info, AgentPassport>,
    pub owner: Signer<'info>,
}

#[derive(Accounts)]
pub struct OpenChannel<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(init, payer = user, space = 8 + ChannelState::INIT_SPACE, seeds = [b"channel", user.key().as_ref()], bump)]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct TopUpChannel<'info> {
    #[account(mut, seeds = [b"channel", user.key().as_ref()], bump = channel.bump, has_one = user @ ApertureError::UnauthorizedOwner)]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(task_hash: [u8; 32])]
pub struct StartTask<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut, seeds = [b"channel", channel.user.as_ref()], bump = channel.bump, constraint = channel.oracle == config.oracle @ ApertureError::InvalidOracle)]
    pub channel: Account<'info, ChannelState>,
    #[account(mut, address = config.oracle @ ApertureError::UnauthorizedOracle)]
    pub oracle: Signer<'info>,
    /// CHECK: Immutable configured payment destination; no data is read.
    #[account(mut, address = config.treasury @ ApertureError::InvalidTreasury, constraint = treasury.key() != channel.key() @ ApertureError::InvalidTreasury)]
    pub treasury: UncheckedAccount<'info>,
    #[account(mut)]
    pub passport: Option<Account<'info, AgentPassport>>,
    #[account(init, payer = oracle, space = 8 + TaskReceipt::INIT_SPACE, seeds = [b"task".as_ref(), task_hash.as_ref()], bump)]
    pub receipt: Account<'info, TaskReceipt>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(task_hash: [u8; 32])]
pub struct StopTask<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut, seeds = [b"channel", channel.user.as_ref()], bump = channel.bump, constraint = channel.oracle == config.oracle @ ApertureError::InvalidOracle)]
    pub channel: Account<'info, ChannelState>,
    #[account(address = config.oracle @ ApertureError::UnauthorizedOracle)]
    pub oracle: Signer<'info>,
    /// CHECK: Immutable configured payment destination; no data is read.
    #[account(mut, address = config.treasury @ ApertureError::InvalidTreasury, constraint = treasury.key() != channel.key() @ ApertureError::InvalidTreasury)]
    pub treasury: UncheckedAccount<'info>,
    #[account(mut)]
    pub passport: Option<Account<'info, AgentPassport>>,
    #[account(mut, seeds = [b"task".as_ref(), task_hash.as_ref()], bump = receipt.bump)]
    pub receipt: Account<'info, TaskReceipt>,
}

#[derive(Accounts)]
pub struct UpdateBurnRate<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut, seeds = [b"channel", channel.user.as_ref()], bump = channel.bump, constraint = channel.oracle == config.oracle @ ApertureError::InvalidOracle)]
    pub channel: Account<'info, ChannelState>,
    #[account(address = config.oracle @ ApertureError::UnauthorizedOracle)]
    pub ai_agent: Signer<'info>,
    /// CHECK: Immutable configured payment destination; no data is read.
    #[account(mut, address = config.treasury @ ApertureError::InvalidTreasury)]
    pub treasury: UncheckedAccount<'info>,
}

#[derive(Accounts)]
pub struct CloseChannel<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut, seeds = [b"channel", user.key().as_ref()], bump = channel.bump, has_one = user @ ApertureError::UnauthorizedOwner, constraint = channel.oracle == config.oracle @ ApertureError::InvalidOracle, close = user)]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    /// CHECK: Immutable configured payment destination; no data is read.
    #[account(mut, address = config.treasury @ ApertureError::InvalidTreasury, constraint = treasury.key() != channel.key() @ ApertureError::InvalidTreasury)]
    pub treasury: UncheckedAccount<'info>,
    #[account(mut)]
    pub passport: Option<Account<'info, AgentPassport>>,
    #[account(mut)]
    pub receipt: Option<Account<'info, TaskReceipt>>,
}

#[account]
#[derive(InitSpace)]
pub struct ProtocolConfig {
    pub authority: Pubkey,
    pub oracle: Pubkey,
    pub treasury: Pubkey,
    pub bump: u8,
    pub version: u16,
}

#[account]
#[derive(InitSpace)]
pub struct AgentPassport {
    pub owner: Pubkey,
    pub agent: Pubkey,
    pub metadata_hash: [u8; 32],
    pub max_cost: u64,
    pub max_runtime: u32,
    pub valid_until: i64,
    pub total_budget: u64,
    pub spent: u64,
    pub reserved: u64,
    pub revoked: bool,
    pub revoked_at: i64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct ChannelState {
    // Preserve the v1 prefix; v2 accounts have a different total length.
    pub user: Pubkey,
    pub oracle: Pubkey,
    pub balance: u64,
    pub burn_rate: u64,
    pub last_update_time: i64,
    pub bump: u8,
    pub agent: Pubkey,
    pub task_hash: [u8; 32],
    pub task_max_cost: u64,
    pub task_deadline: i64,
    pub task_started_at: i64,
    pub last_task_hash: [u8; 32],
    pub last_charged: u64,
}

#[account]
#[derive(InitSpace)]
pub struct TaskReceipt {
    pub owner: Pubkey,
    pub agent: Pubkey,
    pub task_hash: [u8; 32],
    pub source_hash: [u8; 32],
    pub rate: u64,
    pub max_cost: u64,
    pub started_at: i64,
    pub deadline: i64,
    pub settled_at: i64,
    pub charged_lamports: u64,
    pub settled: bool,
    pub bump: u8,
}

#[event]
pub struct TaskStartedEvent {
    pub owner: Pubkey,
    pub agent: Pubkey,
    pub task_hash: [u8; 32],
    pub max_cost: u64,
    pub deadline: i64,
    pub rate: u64,
}

#[event]
pub struct TaskSettledEvent {
    pub owner: Pubkey,
    pub agent: Pubkey,
    pub task_hash: [u8; 32],
    pub charged_lamports: u64,
    pub settled_at: i64,
}

#[error_code]
pub enum ApertureError {
    #[msg("Arithmetic overflow occurred during balance calculation")]
    MathOverflow,
    #[msg("Channel has insufficient balance for operation")]
    InsufficientBalance,
    #[msg("Only the configured oracle may authorize task payment state")]
    UnauthorizedOracle,
    #[msg("The channel oracle does not match protocol configuration")]
    InvalidOracle,
    #[msg("The configured treasury public key is invalid")]
    InvalidTreasury,
    #[msg("The requested burn rate is zero or exceeds the protocol maximum")]
    BurnRateTooHigh,
    #[msg("The payment channel has an active task")]
    ChannelBusy,
    #[msg("Build with APERTURE_CONFIG_AUTHORITY set to the intended protocol authority")]
    ConfigAuthorityNotConfigured,
    #[msg("Only the authority pinned into this build may initialize config")]
    UnauthorizedConfigAuthority,
    #[msg("A version 2 protocol configuration is required")]
    InvalidVersion,
    #[msg("Agent policy has invalid cost or total budget")]
    InvalidPolicy,
    #[msg("Runtime exceeds its allowed bound or is zero")]
    InvalidRuntime,
    #[msg("The agent permission has expired")]
    PassportExpired,
    #[msg("Agent allowance would be exceeded")]
    AllowanceExceeded,
    #[msg("An active reservation prevents policy update")]
    PassportBusy,
    #[msg("Hash values must be nonzero")]
    InvalidHash,
    #[msg("The supplied passport or its PDA is invalid")]
    InvalidPassport,
    #[msg("Only the registered owner may manage this agent or channel")]
    UnauthorizedOwner,
    #[msg("The agent public key is invalid or mismatched")]
    InvalidAgent,
    #[msg("The agent permission has been revoked")]
    PassportRevoked,
    #[msg("Task state or receipt does not match the active task")]
    TaskMismatch,
    #[msg("The task reservation accounting is inconsistent")]
    InvalidReservation,
    #[msg("Use start_task and stop_task for bounded task payment")]
    BoundedTaskRequired,
    #[msg("An active task receipt is required to close this channel")]
    MissingReceipt,
    #[msg("Payment recipient must be rent-exempt before it can receive a charge")]
    PaymentRecipientNotRentExempt,
}

#[cfg(test)]
mod tests {
    use super::*;
    use anchor_lang::{AccountSerialize, InstructionData, ToAccountMetas};

    fn passport() -> AgentPassport {
        AgentPassport {
            owner: Pubkey::new_unique(),
            agent: Pubkey::new_unique(),
            metadata_hash: [1; 32],
            max_cost: 100,
            max_runtime: 20,
            valid_until: 120,
            total_budget: 200,
            spent: 0,
            reserved: 0,
            revoked: false,
            revoked_at: 0,
            bump: 1,
        }
    }

    fn task(p: &AgentPassport) -> (ChannelState, TaskReceipt) {
        let channel = ChannelState {
            user: p.owner,
            oracle: Pubkey::new_unique(),
            balance: 500,
            burn_rate: 10,
            last_update_time: 100,
            bump: 1,
            agent: p.agent,
            task_hash: [2; 32],
            task_max_cost: 100,
            task_deadline: 120,
            task_started_at: 100,
            last_task_hash: [0; 32],
            last_charged: 0,
        };
        let receipt = TaskReceipt {
            owner: p.owner,
            agent: p.agent,
            task_hash: [2; 32],
            source_hash: [3; 32],
            rate: 10,
            max_cost: 100,
            started_at: 100,
            deadline: 120,
            settled_at: 0,
            charged_lamports: 0,
            settled: false,
            bump: 1,
        };
        (channel, receipt)
    }

    #[test]
    fn deadline_and_budget_bound_a_late_stop() {
        assert_eq!(bounded_charge(500, 10, 100, 100, 120, 9_999, None), 100);
        assert_eq!(bounded_charge(500, 3, 100, 100, 120, 9_999, None), 60);
        assert_eq!(bounded_charge(17, 10, 100, 100, 120, 9_999, None), 17);
    }

    #[test]
    fn revocation_stops_accrual_and_repeat_revoke_cannot_extend_it() {
        let mut p = passport();
        revoke_passport(&mut p, 104);
        revoke_passport(&mut p, 119);
        assert_eq!(p.revoked_at, 104);
        assert_eq!(
            bounded_charge(500, 10, 100, 100, 120, 200, Some(p.revoked_at)),
            40
        );
    }

    #[test]
    fn backward_clock_and_extreme_values_do_not_overflow() {
        assert_eq!(bounded_charge(500, 10, 100, 100, 120, 90, None), 0);
        assert_eq!(bounded_charge(500, 10, 100, 100, 120, 200, Some(90)), 0);
        assert_eq!(
            bounded_charge(
                u64::MAX,
                u64::MAX,
                u64::MAX,
                i64::MIN,
                i64::MAX,
                i64::MAX,
                None
            ),
            u64::MAX
        );
    }

    #[test]
    fn aggregate_reservations_and_expiry_gate_admission() {
        let mut p = passport();
        let owner = p.owner;
        let agent = p.agent;
        assert_eq!(
            reserve_allowance(&mut p, owner, agent, 100, 20, 110).unwrap(),
            120
        );
        assert_eq!(
            reserve_allowance(&mut p, owner, agent, 100, 20, 110).unwrap(),
            120
        );
        assert!(reserve_allowance(&mut p, owner, agent, 1, 20, 110).is_err());
        assert_eq!(p.reserved, 200);
        assert!(reserve_allowance(&mut p, owner, agent, 1, 20, 120).is_err());
    }

    #[test]
    fn wrong_identity_revocation_and_per_task_limits_are_rejected() {
        let mut p = passport();
        let owner = p.owner;
        let agent = p.agent;
        assert!(reserve_allowance(&mut p, Pubkey::new_unique(), agent, 10, 10, 100).is_err());
        assert!(reserve_allowance(&mut p, owner, Pubkey::new_unique(), 10, 10, 100).is_err());
        assert!(reserve_allowance(&mut p, owner, agent, 101, 10, 100).is_err());
        assert!(reserve_allowance(&mut p, owner, agent, 10, 21, 100).is_err());
        revoke_passport(&mut p, 100);
        assert!(reserve_allowance(&mut p, owner, agent, 10, 10, 100).is_err());
        assert_eq!(p.reserved, 0);
    }

    #[test]
    fn policy_update_preserves_spend_and_requires_released_reservation() {
        let mut p = passport();
        p.spent = 50;
        p.reserved = 10;
        assert!(apply_policy(&mut p, [4; 32], 100, 20, 200, 200, 100).is_err());
        p.reserved = 0;
        assert!(apply_policy(&mut p, [4; 32], 10, 20, 200, 40, 100).is_err());
        apply_policy(&mut p, [4; 32], 100, 20, 200, 200, 100).unwrap();
        assert_eq!(p.spent, 50);
        assert_eq!(p.total_budget, 200);
    }

    #[test]
    fn settlement_releases_full_reservation_and_accounts_only_actual_charge() {
        let mut p = passport();
        p.reserved = 100;
        revoke_passport(&mut p, 104);
        let (mut channel, mut receipt) = task(&p);
        assert_eq!(
            settle_task_state(&mut channel, Some(&mut p), &mut receipt, [2; 32], 300).unwrap(),
            Some(40)
        );
        assert_eq!(p.reserved, 0);
        assert_eq!(p.spent, 40);
        assert_eq!(channel.balance, 460);
        assert!(receipt.settled);
        assert_eq!(receipt.charged_lamports, 40);
        assert_eq!(channel.burn_rate, 0);
        assert_eq!(channel.last_task_hash, [2; 32]);
    }

    #[test]
    fn settled_receipt_retry_cannot_modify_a_newer_task() {
        let mut p = passport();
        p.reserved = 100;
        let (mut channel, mut receipt) = task(&p);
        settle_task_state(&mut channel, Some(&mut p), &mut receipt, [2; 32], 105).unwrap();
        channel.task_hash = [8; 32];
        channel.burn_rate = 20;
        p.reserved = 90;
        assert_eq!(
            settle_task_state(&mut channel, Some(&mut p), &mut receipt, [2; 32], 500).unwrap(),
            None
        );
        assert_eq!(channel.task_hash, [8; 32]);
        assert_eq!(channel.burn_rate, 20);
        assert_eq!(channel.balance, 450);
        assert_eq!(p.reserved, 90);
        assert_eq!(p.spent, 50);
    }

    #[test]
    fn missing_or_inconsistent_reservation_leaves_state_unchanged() {
        let mut p = passport();
        let (mut channel, mut receipt) = task(&p);
        assert!(settle_task_state(&mut channel, None, &mut receipt, [2; 32], 105).is_err());
        assert!(settle_task_state(&mut channel, Some(&mut p), &mut receipt, [2; 32], 105).is_err());
        assert!(!receipt.settled);
        assert_eq!(channel.balance, 500);
        assert_eq!(p.spent, 0);
    }

    #[test]
    fn pda_and_account_owner_are_bound_to_the_agent() {
        let mut p = passport();
        let (key, bump) = Pubkey::find_program_address(&[b"agent", p.agent.as_ref()], &crate::ID);
        p.bump = bump;
        validate_passport_identity(key, &p, p.owner, p.agent).unwrap();
        assert!(validate_passport_identity(Pubkey::new_unique(), &p, p.owner, p.agent).is_err());
        assert!(validate_passport_identity(key, &p, Pubkey::new_unique(), p.agent).is_err());
    }

    #[test]
    fn serialized_account_sizes_and_prefix_offsets_match_client_abi() {
        assert_eq!(8 + ProtocolConfig::INIT_SPACE, 107);
        assert_eq!(8 + AgentPassport::INIT_SPACE, 158);
        assert_eq!(8 + ChannelState::INIT_SPACE, 225);
        assert_eq!(8 + TaskReceipt::INIT_SPACE, 186);
        let p = passport();
        let (channel, receipt) = task(&p);
        let mut bytes = Vec::new();
        channel.try_serialize(&mut bytes).unwrap();
        assert_eq!(bytes.len(), 225);
        assert_eq!(&bytes[8..40], p.owner.as_ref());
        assert_eq!(&bytes[97..129], p.agent.as_ref());
        assert_eq!(&bytes[129..161], &[2; 32]);
        bytes.clear();
        p.try_serialize(&mut bytes).unwrap();
        assert_eq!(bytes.len(), 158);
        bytes.clear();
        receipt.try_serialize(&mut bytes).unwrap();
        assert_eq!(bytes.len(), 186);
        assert_eq!(&bytes[72..104], &[2; 32]);
    }

    #[test]
    fn start_instruction_and_optional_account_sentinel_match_manual_clients() {
        let data = crate::instruction::StartTask {
            task_hash: [2; 32],
            source_hash: [3; 32],
            agent: Pubkey::new_unique(),
            rate: 10,
            max_cost: 100,
            max_runtime: 20,
        }
        .data();
        assert_eq!(data.len(), 124);
        assert_eq!(&data[8..40], &[2; 32]);
        assert_eq!(&data[40..72], &[3; 32]);
        assert_eq!(&data[104..112], &10u64.to_le_bytes());
        let accounts = crate::accounts::StartTask {
            config: Pubkey::new_unique(),
            channel: Pubkey::new_unique(),
            oracle: Pubkey::new_unique(),
            treasury: Pubkey::new_unique(),
            passport: None,
            receipt: Pubkey::new_unique(),
            system_program: system_program::ID,
        }
        .to_account_metas(None);
        assert_eq!(accounts.len(), 7);
        assert!(accounts[2].is_signer && accounts[2].is_writable);
        assert_eq!(accounts[4].pubkey, crate::ID);
        assert!(!accounts[4].is_writable);
        assert!(accounts[5].is_writable);
    }

    #[test]
    fn runtime_overflow_and_spent_overflow_do_not_reserve_funds() {
        let mut p = passport();
        p.valid_until = i64::MAX;
        let owner = p.owner;
        let agent = p.agent;
        assert!(reserve_allowance(&mut p, owner, agent, 10, 20, i64::MAX - 1).is_err());
        assert_eq!(p.reserved, 0);
        p.spent = u64::MAX;
        p.total_budget = u64::MAX;
        assert!(reserve_allowance(&mut p, owner, agent, 10, 20, 100).is_err());
        assert_eq!(p.reserved, 0);
    }
}
