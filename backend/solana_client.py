import os
import sys
import json
import hashlib
import struct
import time
import base64
from urllib.parse import urlparse
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
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

load_dotenv()

DEFAULT_PROGRAM_ID = "A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ"
DEVNET_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
KEYPAIR_PATH = Path(__file__).parent / "oracle_keypair.json"
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

def validate_devnet_rpc_url(value: str) -> str:
    """Reject accidental mainnet configuration before opening any RPC client."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    local = host in {"localhost", "127.0.0.1", "::1"}
    allowed_schemes = {"http", "https"} if local else {"https"}
    if parsed.scheme not in allowed_schemes:
        raise ValueError("Aperture supports Devnet only; remote RPC endpoints must use HTTPS.")
    if not host or (not local and "devnet" not in host and "devnet" not in parsed.path.lower()):
        raise ValueError("Aperture is configured for Devnet; SOLANA_RPC_URL must identify a Devnet endpoint.")
    if parsed.username or parsed.password:
        raise ValueError("SOLANA_RPC_URL must not contain embedded credentials.")
    return value


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
        self.rpc_url = validate_devnet_rpc_url(os.getenv("SOLANA_RPC_URL", DEVNET_RPC_URL))
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        
        # 1. Program ID initialization
        program_id_str = os.getenv("SOLANA_PROGRAM_ID") or DEFAULT_PROGRAM_ID
        try:
            self.program_id = Pubkey.from_string(program_id_str)
        except Exception:
            raise RuntimeError("SOLANA_PROGRAM_ID must be a valid public key; refusing to select another program.") from None
            
        # 2. AI Oracle Keypair (Signer)
        self.ai_signer = self._load_or_create_keypair()
        print(f"🟢 [SOLANA] AI ORACLE SIGNER ONLINE: {self.ai_signer.pubkey()}")
        print(f"🔗 [SOLANA] PROGRAM ID: {self.program_id}")

    def _load_or_create_keypair(self) -> Keypair:
        """Load the configured signer; explicit off-chain mode may use an ephemeral key."""
        env_secret = os.getenv("BACKEND_PRIVATE_KEY")
        if env_secret:
            try:
                secret = json.loads(env_secret)
                if isinstance(secret, list) and len(secret) == 64 and all(type(b) is int and 0 <= b <= 255 for b in secret) and any(b > 0 for b in secret):
                    return Keypair.from_bytes(bytes(secret))
                raise ValueError("Invalid keypair bytes")
            except Exception:
                raise RuntimeError("BACKEND_PRIVATE_KEY is invalid; refusing to replace the configured signing identity.") from None

        if KEYPAIR_PATH.exists():
            try:
                with open(KEYPAIR_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return Keypair.from_bytes(bytes(data))
            except Exception:
                raise RuntimeError("oracle_keypair.json is invalid; refusing to replace the configured signing identity.") from None

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

    def _configured_protocol_authority(self) -> Pubkey:
        authority_str = (os.getenv("APERTURE_CONFIG_AUTHORITY") or "").strip()
        if not authority_str:
            raise ValueError("Set APERTURE_CONFIG_AUTHORITY before using the live payment channel.")
        try:
            authority = Pubkey.from_string(authority_str)
        except Exception as e:
            raise ValueError("APERTURE_CONFIG_AUTHORITY must be a valid Solana public key.") from e
        if authority in (Pubkey.default(), SYSTEM_PROGRAM_ID, self.program_id):
            raise ValueError("APERTURE_CONFIG_AUTHORITY must be a signing-wallet address.")
        return authority

    async def get_protocol_config(self) -> dict | None:
        expected_authority = self._configured_protocol_authority()
        config_pda, _bump = self.get_config_pda()
        response = await self.client.get_account_info(config_pda)
        account = response.value
        if not account or account.owner != self.program_id:
            return None

        data = bytes(account.data)
        discriminator = get_anchor_discriminator("account", "ProtocolConfig")
        if len(data) < 107 or data[:8] != discriminator or struct.unpack('<H', data[105:107])[0] != 2:
            raise ValueError("The configured program has an incompatible ProtocolConfig account layout.")

        authority = Pubkey.from_bytes(data[8:40])
        oracle = Pubkey.from_bytes(data[40:72])
        treasury = Pubkey.from_bytes(data[72:104])
        if authority != expected_authority:
            raise ValueError("On-chain protocol authority does not match APERTURE_CONFIG_AUTHORITY.")
        if oracle != self.ai_signer.pubkey():
            raise ValueError("On-chain oracle does not match BACKEND_PRIVATE_KEY.")

        return {
            "config_pda": config_pda,
            "authority": authority,
            "oracle": oracle,
            "treasury": treasury,
            "bump": data[104],
            "version": 2,
        }

    async def initialize_protocol_config(self, treasury_address: str) -> str | None:
        """Initializes the immutable oracle/treasury config once; never changes an existing payout address."""
        try:
            expected_authority = self._configured_protocol_authority()
            if self.ai_signer.pubkey() != expected_authority:
                raise ValueError("BACKEND_PRIVATE_KEY must match APERTURE_CONFIG_AUTHORITY for initialization.")
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
        if len(data) < 225 or data[:8] != discriminator:
            return None
        stored_user = Pubkey.from_bytes(data[8:40])
        if stored_user != user_pubkey:
            return None
        balance = struct.unpack('<Q', data[72:80])[0]
        rate = struct.unpack('<Q', data[80:88])[0]
        last_update = struct.unpack('<q', data[88:96])[0]
        deadline = struct.unpack('<q', data[169:177])[0]
        elapsed = max(0, min(int(time.time()), deadline) - last_update) if rate else 0
        max_cost = struct.unpack('<Q', data[161:169])[0]
        accrued = min(balance, max_cost, elapsed * rate)
        return {
            "channel_pda": channel_pda,
            "oracle": Pubkey.from_bytes(data[40:72]),
            "balance_lamports": balance,
            "effective_balance_lamports": balance - accrued,
            "burn_rate_lamports": rate,
            "last_update_time": last_update,
            "agent_pubkey": str(Pubkey.from_bytes(data[97:129])),
            "task_hash": data[129:161].hex(),
            "task_max_cost_lamports": max_cost,
            "task_deadline": deadline,
            "task_started_at": struct.unpack('<q', data[177:185])[0],
            "last_task_hash": data[185:217].hex(),
            "last_charged_lamports": struct.unpack('<Q', data[217:225])[0],
        }

    def get_agent_pda(self, agent):
        return Pubkey.find_program_address([b'agent', bytes(Pubkey.from_string(agent))], self.program_id)[0]

    def get_task_receipt_pda(self, task_hash):
        return Pubkey.find_program_address([b'task', bytes.fromhex(task_hash)], self.program_id)[0]

    async def get_task_receipt(self, task_hash):
        address = self.get_task_receipt_pda(task_hash)
        response = await self.client.get_account_info(address)
        account = response.value
        if not account or account.owner != self.program_id:
            return None
        data = bytes(account.data)
        if len(data) < 186 or data[:8] != get_anchor_discriminator('account', 'TaskReceipt') or data[72:104].hex() != task_hash:
            raise ValueError('Incompatible task receipt or incorrect task hash.')
        return {'receipt_pda': str(address), 'owner': str(Pubkey.from_bytes(data[8:40])),
                'agent_pubkey': str(Pubkey.from_bytes(data[40:72])), 'task_hash': data[72:104].hex(),
                'source_hash': data[104:136].hex(), 'rate_lamports': struct.unpack('<Q', data[136:144])[0],
                'max_cost_lamports': struct.unpack('<Q', data[144:152])[0],
                'started_at': struct.unpack('<q', data[152:160])[0], 'deadline': struct.unpack('<q', data[160:168])[0],
                'settled_at': struct.unpack('<q', data[168:176])[0], 'charged_lamports': struct.unpack('<Q', data[176:184])[0],
                'settled': bool(data[184])}

    async def _receipt_settlement(self, receipt):
        signature = None
        try:
            signatures = await self.client.get_signatures_for_address(Pubkey.from_string(receipt['receipt_pda']), limit=20)
            for record in signatures.value:
                if record.err is None:
                    signature = str(record.signature)
                    break
        except Exception:
            pass
        return {'signature': signature, 'charged_lamports': receipt['charged_lamports'],
                'evidence': 'confirmed_task_receipt', 'receipt_pda': receipt['receipt_pda']}

    async def get_agent_passport(self, agent):
        address = self.get_agent_pda(agent)
        response = await self.client.get_account_info(address)
        account = response.value
        if not account or account.owner != self.program_id:
            return None
        data = bytes(account.data)
        if len(data) < 158 or data[:8] != get_anchor_discriminator('account', 'AgentPassport'):
            raise ValueError('Incompatible on-chain agent passport layout.')
        stored_agent = str(Pubkey.from_bytes(data[40:72]))
        if stored_agent != agent:
            raise ValueError('Agent passport key mismatch.')
        return {'passport_pda': str(address), 'owner': str(Pubkey.from_bytes(data[8:40])),
                'agent_pubkey': stored_agent, 'metadata_hash': data[72:104].hex(),
                'max_cost_lamports': struct.unpack('<Q', data[104:112])[0],
                'max_runtime_seconds': struct.unpack('<I', data[112:116])[0],
                'valid_until': struct.unpack('<q', data[116:124])[0],
                'total_budget_lamports': struct.unpack('<Q', data[124:132])[0],
                'spent_lamports': struct.unpack('<Q', data[132:140])[0],
                'reserved_lamports': struct.unpack('<Q', data[140:148])[0],
                'revoked': bool(data[148]), 'revoked_at': struct.unpack('<q', data[149:157])[0]}

    def agent_instruction(self, action, policy):
        """Prepare public instruction bytes; only the owner wallet signs it."""
        agent = Pubkey.from_string(policy['agent_pubkey'])
        owner = Pubkey.from_string(policy['owner'])
        passport = self.get_agent_pda(policy['agent_pubkey'])
        name = {'register': 'register_agent', 'update': 'update_agent', 'revoke': 'revoke_agent'}[action]
        data = get_anchor_discriminator('global', name)
        if action != 'revoke':
            data += bytes.fromhex(policy['metadata_hash']) + struct.pack('<QI qQ', policy['max_cost_lamports'], policy['max_runtime_seconds'], policy['expires_at'], policy['total_budget_lamports'])
        accounts = [AccountMeta(passport, False, True), AccountMeta(owner, True, True)]
        if action == 'register':
            accounts += [AccountMeta(agent, False, False), AccountMeta(SYSTEM_PROGRAM_ID, False, False)]
        return {'program_id': str(self.program_id), 'kind': action, 'data': list(data), 'data_base64': base64.b64encode(data).decode('ascii'), 'accounts': [
            {'pubkey': str(account.pubkey), 'is_signer': account.is_signer, 'is_writable': account.is_writable} for account in accounts]}

    async def _build_task_instruction(self, name, owner, task_hash, agent, extra=b''):
        config = await self.get_protocol_config()
        if not config:
            raise RuntimeError('Compatible v2 protocol config is required.')
        channel, _ = self.get_channel_pda(Pubkey.from_string(owner))
        passport = self.get_agent_pda(agent) if agent != owner else self.program_id
        receipt = self.get_task_receipt_pda(task_hash)
        accounts = [
            AccountMeta(config['config_pda'], False, False), AccountMeta(channel, False, True),
            AccountMeta(self.ai_signer.pubkey(), True, name == 'start_task'), AccountMeta(config['treasury'], False, True),
            AccountMeta(passport, False, agent != owner), AccountMeta(receipt, False, True)]
        if name == 'start_task':
            accounts.append(AccountMeta(SYSTEM_PROGRAM_ID, False, False))
        return Instruction(self.program_id, get_anchor_discriminator('global', name) + bytes.fromhex(task_hash) + extra, accounts)

    async def _task_instruction(self, name, owner, task_hash, agent, extra=b''):
        return await self._send_and_confirm(await self._build_task_instruction(name, owner, task_hash, agent, extra))

    async def prepare_start_task(self, owner, task_hash, source_hash, agent, rate, max_cost, max_runtime):
        extra = bytes.fromhex(source_hash) + bytes(Pubkey.from_string(agent)) + struct.pack('<QQI', rate, max_cost, max_runtime)
        instruction = await self._build_task_instruction('start_task', owner, task_hash, agent, extra)
        latest = await self.client.get_latest_blockhash()
        message = Message.new_with_blockhash([instruction], self.ai_signer.pubkey(), latest.value.blockhash)
        transaction = VersionedTransaction(message, [self.ai_signer])
        return {'transaction': base64.b64encode(bytes(transaction)).decode('ascii'),
                'signature': str(transaction.signatures[0]), 'last_valid_block_height': latest.value.last_valid_block_height}

    async def send_prepared_start(self, prepared):
        transaction = VersionedTransaction.from_bytes(base64.b64decode(prepared['transaction']))
        if str(transaction.signatures[0]) != prepared['signature']:
            raise ValueError('Prepared transaction signature does not match stored start intent.')
        sent = await self.client.send_transaction(transaction)
        if str(sent.value) != prepared['signature']:
            raise RuntimeError('RPC returned an unexpected transaction signature.')
        confirmation = await self.client.confirm_transaction(sent.value, commitment=Confirmed,
                                                            last_valid_block_height=prepared['last_valid_block_height'])
        status = confirmation.value[0] if confirmation.value else None
        if not status or status.err:
            raise RuntimeError('Task start transaction was not confirmed successfully.')
        return prepared['signature']

    async def start_task(self, owner, task_hash, source_hash, agent, rate, max_cost, max_runtime):
        prepared = await self.prepare_start_task(owner, task_hash, source_hash, agent, rate, max_cost, max_runtime)
        return await self.send_prepared_start(prepared)

    async def stop_task(self, owner, task_hash, agent, start_intent=None):
        receipt = await self.get_task_receipt(task_hash)
        if receipt:
            if receipt['owner'] != owner or receipt['agent_pubkey'] != agent:
                raise ValueError('Task receipt ownership does not match this execution.')
            if receipt['settled']:
                return await self._receipt_settlement(receipt)
        if not receipt:
            if not start_intent:
                return None
            # A start could land after the gateway died. A missing account only
            # proves no spend after its signed blockhash has expired.
            height = await self.client.get_block_height(commitment=Confirmed)
            if height.value <= start_intent['last_valid_block_height']:
                return None
            statuses = await self.client.get_signature_statuses([Signature.from_string(start_intent['signature'])], search_transaction_history=True)
            status = statuses.value[0] if statuses.value else None
            if status is None or status.err is not None:
                return {'signature': None, 'charged_lamports': 0, 'evidence': 'expired_unlanded_start_transaction'}
            return None
        state = await self.get_channel_state(owner)
        if not state:
            return None
        if state['last_task_hash'] == task_hash and not state['burn_rate_lamports']:
            return {'signature': None, 'charged_lamports': state['last_charged_lamports'], 'evidence': 'confirmed_channel_state'}
        # Never stop another task/channel session after a delayed retry.
        if state['task_hash'] != task_hash:
            return None
        signature = await self._task_instruction('stop_task', owner, task_hash, agent)
        final = await self.get_task_receipt(task_hash)
        if not final or not final['settled'] or final['owner'] != owner:
            return None
        return {'signature': signature, 'charged_lamports': final['charged_lamports'], 'evidence': 'confirmed_task_receipt', 'receipt_pda': final['receipt_pda']}

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
