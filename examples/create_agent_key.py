"""Create a dedicated local agent identity; print only its public key."""
import argparse
import json
import os
from pathlib import Path
from solders.keypair import Keypair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    key = Keypair()
    # Exclusive creation preserves an existing identity and its recovery journal.
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(list(bytes(key)), target)
    print("Agent public key: " + str(key.pubkey()))
    print("Private key saved locally to: " + str(args.output.resolve()))


if __name__ == "__main__":
    main()
