use anchor_lang::prelude::*;
use anchor_lang::system_program;

// Unique program ID on Solana Devnet
declare_id!("C2q9yxux7b7bxFF64pkZUV6g2Vcs2bQ1FS4GUQy512wv");

pub const MAX_BURN_RATE_LAMPORTS_PER_SECOND: u64 = 25_000;

#[program]
pub mod aperture_gateway {
    use super::*;

    /// Initializes the protocol-wide oracle and payout destination once.
    pub fn initialize_config(ctx: Context<InitializeConfig>, treasury: Pubkey) -> Result<()> {
        require!(treasury != Pubkey::default(), ApertureError::InvalidTreasury);
        require!(treasury != system_program::ID, ApertureError::InvalidTreasury);
        require!(treasury != crate::ID, ApertureError::InvalidTreasury);

        let config = &mut ctx.accounts.config;
        config.authority = ctx.accounts.authority.key();
        config.oracle = ctx.accounts.authority.key();
        config.treasury = treasury;
        config.bump = ctx.bumps.config;
        Ok(())
    }

    /// Initializes a streaming payment channel PDA for the user.
    /// Locks initial SOL into the contract to fuel autonomous AI compute workloads.
    pub fn open_channel(
        ctx: Context<OpenChannel>,
        initial_deposit: u64,
    ) -> Result<()> {
        require!(initial_deposit > 0, ApertureError::InsufficientBalance);
        let channel_info = ctx.accounts.channel.to_account_info();
        let channel = &mut ctx.accounts.channel;
        channel.user = ctx.accounts.user.key();
        channel.oracle = ctx.accounts.config.oracle;
        channel.burn_rate = 0; // Burn rate initially 0 (standby)
        channel.last_update_time = Clock::get()?.unix_timestamp;
        channel.bump = ctx.bumps.channel;

        // CPI transfer of deposited SOL into the channel account
        if initial_deposit > 0 {
            let cpi_context = CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.user.to_account_info(),
                    to: channel_info.clone(),
                },
            );
            system_program::transfer(cpi_context, initial_deposit)?;
        }

        // Count any SOL that was sent to this PDA before initialization too.
        // Only the rent-exempt reserve is excluded from spendable channel funds.
        let rent_reserve = Rent::get()?.minimum_balance(channel_info.data_len());
        channel.balance = channel_info.lamports().saturating_sub(rent_reserve);

        msg!(
            "Aperture: Channel opened for {}. Oracle: {}. Deposit: {} lamports",
            channel.user,
            channel.oracle,
            initial_deposit
        );
        Ok(())
    }

    /// Tops up an existing payment channel with additional fuel (lamports).
    pub fn top_up(ctx: Context<TopUpChannel>, amount: u64) -> Result<()> {
        let channel_info = ctx.accounts.channel.to_account_info();
        let channel = &mut ctx.accounts.channel;
        require!(channel.burn_rate == 0, ApertureError::ChannelBusy);
        require!(amount > 0, ApertureError::InsufficientBalance);
        channel.balance = channel
            .balance
            .checked_add(amount)
            .ok_or(ApertureError::MathOverflow)?;

        let cpi_context = CpiContext::new(
            ctx.accounts.system_program.to_account_info(),
            system_program::Transfer {
                from: ctx.accounts.user.to_account_info(),
                to: channel_info,
            },
        );
        system_program::transfer(cpi_context, amount)?;

        msg!(
            "Aperture: Topped up {} lamports. Total balance: {}",
            amount,
            channel.balance
        );
        Ok(())
    }

    /// Applies the previous rate and transfers the elapsed charge to the configured treasury.
    pub fn update_burn_rate(ctx: Context<UpdateBurnRate>, new_rate: u64) -> Result<()> {
        require!(
            new_rate <= MAX_BURN_RATE_LAMPORTS_PER_SECOND,
            ApertureError::BurnRateTooHigh
        );
        let channel_info = ctx.accounts.channel.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();
        let channel = &mut ctx.accounts.channel;
        require!(new_rate == 0 || channel.balance > 0, ApertureError::InsufficientBalance);
        require!(channel.oracle == ctx.accounts.config.oracle, ApertureError::InvalidOracle);
        let current_time = Clock::get()?.unix_timestamp;

        // Charge elapsed time under the previous rate and move those SOL now.
        let elapsed_seconds = (current_time.saturating_sub(channel.last_update_time)) as u64;
        let burned_amount = elapsed_seconds.saturating_mul(channel.burn_rate);

        let charged_amount = std::cmp::min(burned_amount, channel.balance);
        if charged_amount > 0 {
            **channel_info.try_borrow_mut_lamports()? -= charged_amount;
            **treasury_info.try_borrow_mut_lamports()? += charged_amount;
        }
        channel.balance -= charged_amount;

        // An exhausted channel cannot continue accruing charges.
        channel.burn_rate = if channel.balance == 0 { 0 } else { new_rate };
        channel.last_update_time = current_time;

        emit!(BurnRateUpdatedEvent {
            user: channel.user,
            new_rate: channel.burn_rate,
            charged_amount,
            remaining_balance: channel.balance,
            timestamp: current_time,
        });

        msg!(
            "Aperture: Burn rate updated to {} lamports/sec. Balance: {}",
            channel.burn_rate,
            channel.balance
        );
        Ok(())
    }

    /// Closes the channel, pays the final elapsed charge to the fixed treasury,
    /// and refunds remaining spendable funds to the user.
    pub fn close_channel(ctx: Context<CloseChannel>) -> Result<()> {
        let channel_info = ctx.accounts.channel.to_account_info();
        let user_info = ctx.accounts.user.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();
        let channel = &mut ctx.accounts.channel;
        require!(channel.oracle == ctx.accounts.config.oracle, ApertureError::InvalidOracle);
        let current_time = Clock::get()?.unix_timestamp;

        let elapsed_seconds = (current_time.saturating_sub(channel.last_update_time)) as u64;
        let burned_amount = elapsed_seconds.saturating_mul(channel.burn_rate);

        let charged_amount = std::cmp::min(burned_amount, channel.balance);
        let refund_amount = channel.balance - charged_amount;

        if charged_amount > 0 || refund_amount > 0 {
            **channel_info.try_borrow_mut_lamports()? -= charged_amount + refund_amount;
            **user_info.try_borrow_mut_lamports()? += refund_amount;
            **treasury_info.try_borrow_mut_lamports()? += charged_amount;
        }

        channel.balance = 0;
        channel.burn_rate = 0;

        msg!(
            "Aperture: Channel closed. Refund: {} lamports, Settled: {} lamports",
            refund_amount,
            charged_amount
        );
        Ok(())
    }
}

// --- Account Contexts ---

#[derive(Accounts)]
pub struct InitializeConfig<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + ProtocolConfig::INIT_SPACE,
        seeds = [b"config"],
        bump
    )]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct OpenChannel<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(
        init,
        payer = user,
        space = 8 + ChannelState::INIT_SPACE,
        seeds = [b"channel", user.key().as_ref()],
        bump
    )]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct TopUpChannel<'info> {
    #[account(
        mut,
        seeds = [b"channel", user.key().as_ref()],
        bump = channel.bump
    )]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateBurnRate<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(
        mut,
        seeds = [b"channel", channel.user.as_ref()],
        bump = channel.bump
    )]
    pub channel: Account<'info, ChannelState>,
    /// The oracle selected by the channel owner when it was opened.
    #[account(address = config.oracle @ ApertureError::UnauthorizedOracle)]
    pub ai_agent: Signer<'info>,
    /// The immutable payout destination stored in protocol config.
    #[account(mut, address = config.treasury @ ApertureError::InvalidTreasury)]
    pub treasury: UncheckedAccount<'info>,
}

#[derive(Accounts)]
pub struct CloseChannel<'info> {
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, ProtocolConfig>,
    #[account(
        mut,
        seeds = [b"channel", user.key().as_ref()],
        bump = channel.bump,
        close = user
    )]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    /// The immutable payout destination stored in protocol config.
    #[account(mut, address = config.treasury @ ApertureError::InvalidTreasury)]
    pub treasury: UncheckedAccount<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct ProtocolConfig {
    pub authority: Pubkey,
    pub oracle: Pubkey,
    pub treasury: Pubkey,
    pub bump: u8,
}

// --- State Structs ---

#[account]
#[derive(InitSpace)]
pub struct ChannelState {
    pub user: Pubkey,
    pub oracle: Pubkey,
    pub balance: u64,
    pub burn_rate: u64,
    pub last_update_time: i64,
    pub bump: u8,
}

// --- Events & Errors ---

#[event]
pub struct BurnRateUpdatedEvent {
    pub user: Pubkey,
    pub new_rate: u64,
    pub charged_amount: u64,
    pub remaining_balance: u64,
    pub timestamp: i64,
}

#[error_code]
pub enum ApertureError {
    #[msg("Arithmetic overflow occurred during balance calculation")]
    MathOverflow,
    #[msg("Channel has insufficient balance for operation")]
    InsufficientBalance,
    #[msg("Only the channel's configured oracle may update its burn rate")]
    UnauthorizedOracle,
    #[msg("A payment channel requires a valid oracle public key")]
    InvalidOracle,
    #[msg("The configured treasury public key is invalid")]
    InvalidTreasury,
    #[msg("The requested burn rate exceeds the protocol maximum")]
    BurnRateTooHigh,
    #[msg("A payment channel cannot be topped up while a task is running")]
    ChannelBusy,
}
