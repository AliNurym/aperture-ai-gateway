#!/usr/bin/env python3
"""03_passport_delegation_flow.py

Aperture Example 3: Cryptographic Agent Passport Delegation Lifecycle
Demonstrates how a human owner issues an on-chain/gateway cryptographic
delegation (Agent Passport) to an autonomous agent keypair, constraining
per-run cost, total allowance, execution time, and expiration.
"""
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from solders.keypair import Keypair
from nacl.signing import VerifyKey
import base58

from agent_identity import canonical_json, sha256_text


def run_passport_delegation_demo():
    print("===================================================================")
    print("  APERTURE PASSPORT DEMO: Delegated Cryptographic Identity Lifecycle")
    print("===================================================================")

    # 1. Generate Principal (Owner) and Autonomous Agent Keypairs
    owner_keypair = Keypair()
    agent_keypair = Keypair()

    owner_pubkey_str = str(owner_keypair.pubkey())
    agent_pubkey_str = str(agent_keypair.pubkey())

    print("\n[Step 1] Keypair Generation:")
    print(f"  * Principal Owner Wallet: {owner_pubkey_str}")
    print(f"  * Delegated Agent Key:    {agent_pubkey_str}")
    print("  🔒 Separation of Concerns: The Agent NEVER possesses the Owner's private key.")

    # 2. Define the Agent Passport Delegation Policy
    validity_duration_seconds = 86_400  # 24 Hours
    expires_at = int(time.time()) + validity_duration_seconds

    passport_policy = {
        "action": "register",
        "owner": owner_pubkey_str,
        "agent_pubkey": agent_pubkey_str,
        "name": "Portfolio Risk Sentinel v2",
        "max_cost_lamports": 50_000,          # 0.00005 SOL max per task
        "max_runtime_seconds": 20,            # 20s maximum execution window
        "total_budget_lamports": 500_000,     # 0.0005 SOL lifetime ceiling
        "expires_at": expires_at,
        "capabilities": ["python.execute"],
    }

    print("\n[Step 2] Defining Cryptographic Passport Policy:")
    print(f"  * Per-Task Cost Cap:    {passport_policy['max_cost_lamports']:,} lamports")
    print(f"  * Per-Task Runtime Cap: {passport_policy['max_runtime_seconds']}s")
    print(f"  * Total Budget Ceiling: {passport_policy['total_budget_lamports']:,} lamports")
    print(f"  * Expiry:               {time.ctime(expires_at)} (24 hours)")
    print(f"  * Allowed Capabilities: {passport_policy['capabilities']}")

    # 3. Canonical Serialization & Owner Signature
    # Both gateway and Solana on-chain contract enforce deterministic canonical JSON
    canonical_policy_bytes = canonical_json(passport_policy).encode("utf-8")
    policy_hash = sha256_text(canonical_policy_bytes.decode("utf-8"))

    # Owner signs the challenge with their master private key
    owner_signature = owner_keypair.sign_message(canonical_policy_bytes)
    owner_sig_bytes = bytes(owner_signature)

    print("\n[Step 3] Owner Issues & Signs Passport Delegation:")
    print(f"  * Policy SHA256 Hash: {policy_hash}")
    print(f"  * Ed25519 Signature:  {base58.b58encode(owner_sig_bytes).decode('ascii')[:32]}...")

    # 4. Verification of Owner Delegation by Gateway / Validator
    verify_key = VerifyKey(bytes(owner_keypair.pubkey()))
    try:
        verify_key.verify(canonical_policy_bytes, owner_sig_bytes)
        print("  -> Cryptographic verification PASSED: Signature strictly matches Owner public key.")
    except Exception as e:
        print(f"  ❌ Signature verification failed: {e}")
        sys.exit(1)

    # 5. Autonomous Agent Invocation (Compliant with Passport)
    print("\n[Step 4] Agent Dispatches Compliant Workload:")
    compliant_task_budget = 40_000  # <= 50,000 lamports
    compliant_runtime = 10          # <= 20 seconds
    print(f"  * Agent requested task budget: {compliant_task_budget:,} lamports (under 50,000 cap)")
    print(f"  * Agent requested runtime:     {compliant_runtime}s (under 20s cap)")

    within_limits = (
        compliant_task_budget <= passport_policy["max_cost_lamports"]
        and compliant_runtime <= passport_policy["max_runtime_seconds"]
        and time.time() < passport_policy["expires_at"]
    )
    assert within_limits, "Policy validation check failed"
    print("  -> Gateway Admission Decision: ADMITTED (Within delegated bounds)")

    # 6. Autonomous Agent Attempting to Exceed Limits (Malicious or Runaway)
    print("\n[Step 5] Simulating Runaway Agent (Exceeding Delegated Caps):")
    rogue_task_budget = 200_000  # Exceeds 50,000 lamports limit!
    print(f"  * Rogue Agent requests task budget: {rogue_task_budget:,} lamports (> 50,000 cap!)")

    violates_limits = rogue_task_budget > passport_policy["max_cost_lamports"]
    if violates_limits:
        print("  -> Gateway Admission Decision: REJECTED WITH HTTP 403")
        print(f"     Reason: Requested budget {rogue_task_budget} exceeds delegated passport cap {passport_policy['max_cost_lamports']}.")
        print("  🛡️ Principal treasury successfully protected from runaway compute consumption.")

    # 7. Owner Inbox Workflow Delegation & Emergency Stop
    print("\n[Step 6] Owner Workflow Inbox Delegation & Emergency Control:")
    workflow_id = "wf-7c491e0a8b2d3f"
    assigned_plan = {
        "workflow_id": workflow_id,
        "owner": owner_pubkey_str,
        "agent_pubkey": agent_pubkey_str,
        "max_cost_lamports": 150_000,
        "steps_count": 3,
        "status": "assigned",
    }
    print(f"  * Owner assigns Workflow ID: {workflow_id}")
    print(f"  * Approved Workflow Ceiling: {assigned_plan['max_cost_lamports']:,} lamports")
    print(f"  * Delegated Recipient:       {agent_pubkey_str}")
    print("  * Agent admits steps autonomously using ONLY Agent key.")
    print("  * Owner retains emergency STOP authority signed with 'Aperture owner control v1'.")

    # Simulate Owner Emergency Stop Signature
    stop_message = f"Aperture owner control v1\naction:stop-workflow\nworkflow_id:{workflow_id}"
    owner_stop_sig = owner_keypair.sign_message(stop_message.encode("utf-8"))
    verify_key.verify(stop_message.encode("utf-8"), bytes(owner_stop_sig))
    print("  -> Owner Emergency Stop Signature VERIFIED: Immediate halt without leaking agent state.")

    print("\n✅ Agent Passport delegation & Owner Inbox lifecycle demonstrated with complete cryptographic verification.")


if __name__ == "__main__":
    run_passport_delegation_demo()

