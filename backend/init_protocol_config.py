import asyncio
import os

from solana_client import SolanaClient


async def main() -> None:
    treasury = (os.getenv("APERTURE_TREASURY_PUBKEY") or "").strip()
    if not treasury:
        raise SystemExit("Set APERTURE_TREASURY_PUBKEY in backend/.env before initialization.")

    client = SolanaClient()
    try:
        signature = await client.initialize_protocol_config(treasury)
        if signature:
            print(f"Protocol config initialized. Treasury: {treasury}. Transaction: {signature}")
        else:
            print(f"Protocol config already uses this treasury: {treasury}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

