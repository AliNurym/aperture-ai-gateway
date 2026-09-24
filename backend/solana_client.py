import os
import sys
import json
import hashlib
import struct
from pathlib import Path
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

load_dotenv()

DEFAULT_PROGRAM_ID = "C2q9yxux7b7bxFF64pkZUV6g2Vcs2bQ1FS4GUQy512wv"
DEVNET_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
KEYPAIR_PATH = Path(__file__).parent / "oracle_keypair.json"
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")


def get_anchor_discriminator(namespace: str, name: str) -> bytes:
    """Calculates Anchor 8-byte discriminator: sha256(f'{namespace}:{name}')[:8]"""
    preimage = f"{namespace}:{name}".encode("utf-8")
    return hashlib.sha256(preimage).digest()[:8]


class SolanaClient:
    """
    Aperture AI-Sentinel On-Chain Gateway Client.
    Manages payment channels, PDA derivation, real-time burn-rate updates,
    and on-chain settlements on Solana Devnet.
    """
    def __init__(self):
        self.rpc_url = os.getenv("SOLANA_RPC_URL", DEVNET_RPC_URL)
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        
        # 1. Program ID initialization
        program_id_str = os.getenv("SOLANA_PROGRAM_ID") or DEFAULT_PROGRAM_ID
        try:
            self.program_id = Pubkey.from_string(program_id_str)
        except Exception:
            self.program_id = Pubkey.from_string(DEFAULT_PROGRAM_ID)
            
        # 2. AI Oracle Keypair (Signer)
        self.ai_signer = self._load_or_create_keypair()
        print(f"🟢 [SOLANA] AI ORACLE SIGNER ONLINE: {self.ai_signer.pubkey()}")
        print(f"🔗 [SOLANA] PROGRAM ID: {self.program_id}")

    def _load_or_create_keypair(self) -> Keypair:
        """Loads keypair from .env, local JSON, or creates a persistent new one."""
        env_secret = os.getenv("BACKEND_PRIVATE_KEY")
        if env_secret:
            try:
                secret = json.loads(env_secret)
                if len(secret) == 64 and any(b > 0 for b in secret):
                    return Keypair.from_bytes(bytes(secret))
            except Exception:
                pass

        if KEYPAIR_PATH.exists():
            try:
                with open(KEYPAIR_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return Keypair.from_bytes(bytes(data))
            except Exception as e:
                print(f"[!] Warning reading oracle_keypair.json: {e}")

        if os.getenv("APERTURE_DEMO_MODE", "false").lower() == "true":
            # Explicit demos may use an ephemeral signer, but never write secrets to disk.
            return Keypair()

        raise RuntimeError("BACKEND_PRIVATE_KEY or oracle_keypair.json is required; refusing to create a secret automatically.")

    def get_channel_pda(self, user_pubkey: Pubkey) -> tuple[Pubkey, int]:
        """Derives the Channel PDA: seeds = [b"channel", user_pubkey]"""
        return Pubkey.find_program_address([b"channel", bytes(user_pubkey)], self.program_id)

    def get_config_pda(self) -> tuple[Pubkey, int]:
        """Derives the singleton protocol configuration PDA."""
        return Pubkey.find_program_address([b"config"], self.program_id)

    async def get_protocol_config(self) -> dict | None:
        config_pda, _bump = self.get_config_pda()
        response = await self.client.get_account_info(config_pda)
        account = response.value
        if not account or account.owner != self.program_id:
            return None

        data = bytes(account.data)
        discriminator = get_anchor_discriminator("account", "ProtocolConfig")
        if len(data) < 105 or data[:8] != discriminator:
            raise ValueError("The configured program has an incompatible ProtocolConfig account layout.")

        authority = Pubkey.from_bytes(data[8:40])
        oracle = Pubkey.from_bytes(data[40:72])
        treasury = Pubkey.from_bytes(data[72:104])
        if oracle != self.ai_signer.pubkey():
            raise ValueError("On-chain oracle does not match BACKEND_PRIVATE_KEY.")

        return {
            "config_pda": config_pda,
            "authority": authority,
            "oracle": oracle,
            "treasury": treasury,
            "bump": data[104],
        }

    async def initialize_protocol_config(self, treasury_address: str) -> str | None:
        """Initializes the immutable oracle/treasury config once; never changes an existing payout address."""
        try:
            treasury = Pubkey.from_string(treasury_address)
            if treasury in (Pubkey.default(), SYSTEM_PROGRAM_ID, self.program_id):
                raise ValueError("APERTURE_TREASURY_PUBKEY must be a wallet address, not a program address.")

            existing = await self.get_protocol_config()
            if existing:
                if existing["treasury"] != treasury:
                    raise ValueError("The deployed protocol config already uses a different treasury address.")
                return None

            config_pda, _bump = self.get_config_pda()
            data = get_anchor_discriminator("global", "initialize_config") + bytes(treasury)
            instruction = Instruction(
                program_id=self.program_id,
                data=data,
                accounts=[
                    AccountMeta(pubkey=config_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=self.ai_signer.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
            )
            signature = await self._send_and_confirm(instruction)
            initialized = await self.get_protocol_config()
            if not initialized or initialized["treasury"] != treasury:
                raise RuntimeError("Protocol config initialization was confirmed but the config account did not match.")
            return signature
        except Exception as e:
            print(f"🔴 [SOLANA] protocol config initialization error: {e}")
            raise

    async def get_channel_state(self, user_pubkey_str: str) -> dict | None:
        """Reads and validates the serialized channel account; prefunded PDAs are not channels."""
        user_pubkey = Pubkey.from_string(user_pubkey_str)
        channel_pda, _bump = self.get_channel_pda(user_pubkey)
        response = await self.client.get_account_info(channel_pda)
        account = response.value
        if not account or account.owner != self.program_id:
            return None

        data = bytes(account.data)
        discriminator = get_anchor_discriminator("account", "ChannelState")
        if len(data) < 97 or data[:8] != discriminator:
            return None
        stored_user = Pubkey.from_bytes(data[8:40])
        if stored_user != user_pubkey:
            return None
        return {
            "channel_pda": channel_pda,
            "oracle": Pubkey.from_bytes(data[40:72]),
            "balance_lamports": struct.unpack("<Q", data[72:80])[0],
            "burn_rate_lamports": struct.unpack("<Q", data[80:88])[0],
        }

    async def get_channel_balance(self, user_pubkey_str: str) -> int:
        """
        Reads user's locked payment channel balance directly from Solana Devnet.
        Returns balance in Lamports.
        """
        state = await self.get_channel_state(user_pubkey_str)
        return state["balance_lamports"] if state else 0

    async def _send_and_confirm(self, instruction: Instruction) -> str:
        latest = await self.client.get_latest_blockhash()
        msg = Message.new_with_blockhash([instruction], self.ai_signer.pubkey(), latest.value.blockhash)
        tx = VersionedTransaction(msg, [self.ai_signer])
        sent = await self.client.send_transaction(tx)
        confirmation = await self.client.confirm_transaction(
            sent.value,
            commitment=Confirmed,
            last_valid_block_height=latest.value.last_valid_block_height,
        )
        statuses = confirmation.value
        status = statuses[0] if statuses else None
        if status is None:
            raise RuntimeError("Solana RPC did not return a confirmation status.")
        if status.err is not None:
            raise RuntimeError(f"Solana transaction failed: {status.err}")
        return str(sent.value)

    async def update_burn_rate(self, user_pubkey_str: str, new_rate_lamports: int) -> str | None:
        """
        Executes update_burn_rate on the smart contract.
        Updates the per-second lamport burn rate dictated by the AI Sentinel.
        """
        try:
            user_pubkey = Pubkey.from_string(user_pubkey_str)
            channel_pda, _bump = self.get_channel_pda(user_pubkey)

            config = await self.get_protocol_config()
            if not config:
                raise RuntimeError("Protocol config is not initialized. Run backend/init_protocol_config.py first.")

            discriminator = get_anchor_discriminator("global", "update_burn_rate")
            rate_bytes = struct.pack("<Q", new_rate_lamports)
            ix_data = discriminator + rate_bytes

            ix = Instruction(
                program_id=self.program_id,
                data=ix_data,
                accounts=[
                    AccountMeta(pubkey=config["config_pda"], is_signer=False, is_writable=False),
                    AccountMeta(pubkey=channel_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=self.ai_signer.pubkey(), is_signer=True, is_writable=False),
                    AccountMeta(pubkey=config["treasury"], is_signer=False, is_writable=True),
                ]
            )
            tx_sig = await self._send_and_confirm(ix)
            print(f"✅ [ON-CHAIN] Burn rate updated ({new_rate_lamports} lamports/sec). TX: {tx_sig}")
            return tx_sig

        except Exception as e:
            print(f"🔴 [SOLANA] update_burn_rate error: {e}")
            return None

    async def request_airdrop(self, pubkey_str: str, lamports: int = 1_000_000_000) -> bool:
        """Helper to fund test wallets on Solana Devnet."""
        try:
            target = Pubkey.from_string(pubkey_str)
            resp = await self.client.request_airdrop(target, lamports)
            print(f"💧 [AIRDROP] Sent {lamports / 1e9} SOL to {pubkey_str}: {resp.value}")
            return True
        except Exception as e:
            print(f"⚠️ [AIRDROP FAILED]: {e}")
            return False

    async def close(self):
        await self.client.close()
