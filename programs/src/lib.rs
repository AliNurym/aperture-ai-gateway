use anchor_lang::prelude::*;
use anchor_lang::system_program;

// Unique program ID on Solana Devnet
declare_id!("C2q9yxux7b7bxFF64pkZUV6g2Vcs2bQ1FS4GUQy512wv");

#[program]
pub mod aperture_gateway {
    use super::*;

    /// Initializes a streaming payment channel PDA for the user.
    /// Locks initial SOL into the contract to fuel autonomous AI compute workloads.
    pub fn open_channel(ctx: Context<OpenChannel>, initial_deposit: u64) -> Result<()> {
        let channel = &mut ctx.accounts.channel;
        channel.user = ctx.accounts.user.key();
        channel.balance = initial_deposit;
        channel.burn_rate = 0; // Burn rate initially 0 (standby)
        channel.last_update_time = Clock::get()?.unix_timestamp;
        channel.bump = ctx.bumps.channel;

        // CPI transfer of deposited SOL into the channel account
        if initial_deposit > 0 {
            let cpi_context = CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.user.to_account_info(),
                    to: ctx.accounts.channel.to_account_info(),
                },
            );
            system_program::transfer(cpi_context, initial_deposit)?;
        }

        msg!("Aperture: Channel opened for {}. Deposit: {} lamports", channel.user, initial_deposit);
        Ok(())
    }

    /// Tops up an existing payment channel with additional fuel (lamports).
    pub fn top_up(ctx: Context<TopUpChannel>, amount: u64) -> Result<()> {
        let channel = &mut ctx.accounts.channel;
        channel.balance = channel.balance.checked_add(amount).ok_or(ApertureError::MathOverflow)?;

        let cpi_context = CpiContext::new(
            ctx.accounts.system_program.to_account_info(),
            system_program::Transfer {
                from: ctx.accounts.user.to_account_info(),
                to: ctx.accounts.channel.to_account_info(),
            },
        );
        system_program::transfer(cpi_context, amount)?;

        msg!("Aperture: Topped up {} lamports. Total balance: {}", amount, channel.balance);
        Ok(())
    }

    /// AI-Sentinel updates the dynamic burn rate on-chain based on code complexity.
    /// Consumed balance is deducted based on elapsed seconds and previous rate.
    pub fn update_burn_rate(ctx: Context<UpdateBurnRate>, new_rate: u64) -> Result<()> {
        let channel = &mut ctx.accounts.channel;
        let current_time = Clock::get()?.unix_timestamp;

        // Deduct tokens for elapsed time under the previous burn rate
        let elapsed_seconds = (current_time.saturating_sub(channel.last_update_time)) as u64;
        let burned_amount = elapsed_seconds.saturating_mul(channel.burn_rate);

        if channel.balance >= burned_amount {
            channel.balance -= burned_amount;
        } else {
            channel.balance = 0; // Gas exhaustion guard
        }

        // Apply new burn rate dictated by AI Oracle
        channel.burn_rate = new_rate;
        channel.last_update_time = current_time;

        emit!(BurnRateUpdatedEvent {
            user: channel.user,
            new_rate,
            remaining_balance: channel.balance,
            timestamp: current_time,
        });

        msg!("Aperture: Burn rate updated to {} lamports/sec. Balance: {}", new_rate, channel.balance);
        Ok(())
    }

    /// Closes the channel: returns unspent lamports to the user,
    /// and settles burned fees to the treasury or node provider.
    pub fn close_channel(ctx: Context<CloseChannel>) -> Result<()> {
        let channel = &mut ctx.accounts.channel;
        let current_time = Clock::get()?.unix_timestamp;

        let elapsed_seconds = (current_time.saturating_sub(channel.last_update_time)) as u64;
        let burned_amount = elapsed_seconds.saturating_mul(channel.burn_rate);

        let final_burn = std::cmp::min(burned_amount, channel.balance);
        let refund_amount = channel.balance.saturating_sub(final_burn);

        // Disburse lamports
        if refund_amount > 0 {
            **ctx.accounts.channel.to_account_info().try_borrow_mut_lamports()? -= refund_amount;
            **ctx.accounts.user.to_account_info().try_borrow_mut_lamports()? += refund_amount;
        }

        if final_burn > 0 {
            **ctx.accounts.channel.to_account_info().try_borrow_mut_lamports()? -= final_burn;
            **ctx.accounts.treasury.to_account_info().try_borrow_mut_lamports()? += final_burn;
        }

        channel.balance = 0;
        channel.burn_rate = 0;

        msg!("Aperture: Channel closed. Refund: {} lamports, Settled: {} lamports", refund_amount, final_burn);
        Ok(())
    }
}

// --- Account Contexts ---

#[derive(Accounts)]
pub struct OpenChannel<'info> {
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
    #[account(mut)]
    pub channel: Account<'info, ChannelState>,
    /// Authorized AI Sentinel Oracle keypair
    pub ai_agent: Signer<'info>,
}

#[derive(Accounts)]
pub struct CloseChannel<'info> {
    #[account(
        mut,
        seeds = [b"channel", user.key().as_ref()],
        bump = channel.bump,
        close = user
    )]
    pub channel: Account<'info, ChannelState>,
    #[account(mut)]
    pub user: Signer<'info>,
    /// CHECK: Treasury or node provider receiving settled compute fees
    #[account(mut)]
    pub treasury: AccountInfo<'info>,
}

// --- State Structs ---

#[account]
#[derive(InitSpace)]
pub struct ChannelState {
    pub user: Pubkey,
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
    pub remaining_balance: u64,
    pub timestamp: i64,
}

#[error_code]
pub enum ApertureError {
    #[msg("Arithmetic overflow occurred during balance calculation")]
    MathOverflow,
    #[msg("Channel has insufficient balance for operation")]
    InsufficientBalance,
}