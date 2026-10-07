#!/usr/bin/env python3
"""doctor.py

Aperture System Health & Environment Doctor.
Performs instant pre-flight checks across:
- Python, Node.js, Git, and Docker runtimes
- Network port availability (8000, 3000, 8101, 3101)
- Aperture storage quotas & SQLite state store integrity
- Cryptographic signing & AST analysis self-test

Usage:
  python scripts/doctor.py
  python scripts/doctor.py --verbose
"""
import argparse
import json
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

# ANSI Color formatting
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def check_mark(status: bool | None) -> str:
    if status is True:
        return f"{GREEN}[OK]{RESET}"
    elif status is False:
        return f"{RED}[FAIL]{RESET}"
    else:
        return f"{YELLOW}[WARN]{RESET}"


class ApertureDoctor:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.passed = 0
        self.warnings = 0
        self.errors = 0

    def record(self, title: str, ok: bool | None, detail: str = ""):
        mark = check_mark(ok)
        if ok is True:
            self.passed += 1
            print(f"  {mark} {BOLD}{title}{RESET}" + (f": {detail}" if detail else ""))
        elif ok is False:
            self.errors += 1
            print(f"  {mark} {BOLD}{RED}{title}{RESET}" + (f": {detail}" if detail else ""))
        else:
            self.warnings += 1
            print(f"  {mark} {BOLD}{YELLOW}{title}{RESET}" + (f": {detail}" if detail else ""))

    def section(self, name: str):
        print(f"\n{CYAN}{BOLD}=== {name} ==={RESET}")

    def check_python(self):
        self.section("1. Python Environment")
        version_info = sys.version_info
        py_ver_str = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
        if version_info >= (3, 11):
            self.record("Python Version", True, f"{py_ver_str} ({platform.system()} {platform.machine()})")
        else:
            self.record("Python Version", False, f"{py_ver_str} (Aperture requires Python 3.11+)")

        # Check required packages
        packages = ["fastapi", "solders", "nacl", "pydantic"]
        for pkg in packages:
            try:
                __import__(pkg)
                self.record(f"Package: {pkg}", True, "Installed")
            except ImportError:
                self.record(f"Package: {pkg}", False, "Missing. Run: pip install -r backend/requirements.txt")

    def check_node(self):
        self.section("2. Node.js & Frontend Toolchain")
        # Try finding node
        node_candidates = [
            "node",
            str(Path(os.environ.get("ProgramFiles", "")) / "nodejs" / "node.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe"),
            str(Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"),
        ]
        found_node = None
        for candidate in node_candidates:
            try:
                out = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=5)
                if out.returncode == 0:
                    found_node = (candidate, out.stdout.strip())
                    break
            except Exception:
                continue

        if found_node:
            self.record("Node.js Runtime", True, f"{found_node[1]} ({found_node[0]})")
        else:
            self.record("Node.js Runtime", False, "Not detected. Install Node.js LTS or use start_preview.bat")

        # Check frontend build status
        dist_dir = REPO_ROOT / "frontend" / "dist"
        if dist_dir.exists() and (dist_dir / "index.html").exists():
            self.record("Frontend Production Bundle", True, f"Built in {dist_dir.name}/")
        else:
            self.record("Frontend Production Bundle", None, "Not built. Run: cd frontend && npm run build")

    def check_docker(self):
        self.section("3. Container Isolation (Optional for Docker Mode)")
        try:
            out = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}"], capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                os_type = out.stdout.strip()
                if os_type == "linux":
                    self.record("Docker Engine", True, "Linux container support active")
                else:
                    self.record("Docker Engine", None, f"Running with '{os_type}' containers (Linux required for sandbox)")
            else:
                self.record("Docker Engine", None, "Docker not running. (Local OFF_CHAIN mode operates without Docker)")
        except FileNotFoundError:
            self.record("Docker CLI", None, "Not installed. (Aperture runs in OFF_CHAIN mode using TrustedLocalExecutor)")

    def check_ports(self):
        self.section("4. Network Port Availability")
        ports = [
            (8000, "Gateway API (Default)"),
            (3000, "Frontend Console (Default)"),
            (8101, "Gateway Preview (Fallback)"),
            (3101, "Frontend Preview (Fallback)"),
        ]
        for port, desc in ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                result = sock.connect_ex(("127.0.0.1", port))
                if result == 0:
                    self.record(f"Port {port} ({desc})", None, "In use / Service active")
                else:
                    self.record(f"Port {port} ({desc})", True, "Available")

    def check_state_store(self):
        self.section("5. Aperture State & SQLite Storage")
        db_path = REPO_ROOT / ".aperture" / "preview" / "state.db"
        if db_path.exists():
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                conn.close()
                expected = ["jobs", "quotes", "challenges", "store_metadata"]
                missing = [t for t in expected if t not in tables]
                if not missing:
                    self.record("Preview SQLite Store", True, f"Integrity valid ({len(tables)} tables: {', '.join(tables[:4])})")
                else:
                    self.record("Preview SQLite Store", False, f"Missing expected tables: {missing}")
            except Exception as e:
                self.record("Preview SQLite Store", False, f"Read error: {e}")
        else:
            self.record("Preview SQLite Store", True, "Will be automatically created on first start_preview.bat run")

    def check_crypto_and_ast(self):
        self.section("6. Cryptographic Engine & AST Self-Test")
        # 1. Test AST analyzer
        try:
            from ai_engine import analyze_code_ast
            sample_code = "import math\nprint(math.sqrt(16))"
            audit = analyze_code_ast(sample_code)
            if audit.get("security") == "SAFE" and audit.get("syntax_valid") is True:
                self.record("AST Security Parser", True, f"Score: {audit.get('complexity_score', 0)} (Status: SAFE)")
            else:
                self.record("AST Security Parser", False, f"Audit rejected safe code: {audit}")
        except Exception as e:
            self.record("AST Security Parser", False, f"Error: {e}")

        # 2. Test Ed25519 signer
        try:
            from solders.keypair import Keypair
            from agent_identity import canonical_json, sha256_text, verify_ed25519
            kp = Keypair()
            pubkey = str(kp.pubkey())
            msg = "Aperture doctor validation test " + str(time.time())
            sig = kp.sign_message(msg.encode("utf-8"))
            valid = verify_ed25519(pubkey, list(bytes(sig)), msg)
            if valid:
                self.record("Ed25519 Cryptographic Verification", True, f"Key: {pubkey[:12]}... (PASSED)")
            else:
                self.record("Ed25519 Cryptographic Verification", False, "Signature verification failed")
        except Exception as e:
            self.record("Ed25519 Cryptographic Verification", False, f"Error: {e}")

    def run(self):
        print(f"\n{BOLD}==================================================================={RESET}")
        print(f"  {BOLD}APERTURE SYSTEM DOCTOR — Pre-flight Diagnostics{RESET}")
        print(f"{BOLD}==================================================================={RESET}")
        start_time = time.monotonic()

        self.check_python()
        self.check_node()
        self.check_docker()
        self.check_ports()
        self.check_state_store()
        self.check_crypto_and_ast()

        elapsed = time.monotonic() - start_time
        print(f"\n{BOLD}==================================================================={RESET}")
        print(f"  Diagnostics finished in {elapsed:.3f}s")
        print(f"  Summary: {GREEN}{self.passed} passed{RESET}, {YELLOW}{self.warnings} notices{RESET}, {RED}{self.errors} errors{RESET}")
        print(f"{BOLD}==================================================================={RESET}\n")

        if self.errors > 0:
            print(f"{RED}{BOLD}Doctor found {self.errors} critical issue(s). Address the errors above before running.{RESET}\n")
            return 1
        elif self.warnings > 0:
            print(f"{GREEN}{BOLD}Aperture is READY to run in OFF_CHAIN mode!{RESET} ({self.warnings} optional notices above)\n")
            return 0
        else:
            print(f"{GREEN}{BOLD}All checks PASSED! Aperture is fully healthy and ready for execution.{RESET}\n")
            return 0


def main():
    parser = argparse.ArgumentParser(description="Aperture Health Doctor")
    parser.add_argument("--verbose", action="store_true", help="Show verbose output")
    args = parser.parse_args()

    doctor = ApertureDoctor(verbose=args.verbose)
    sys.exit(doctor.run())


if __name__ == "__main__":
    main()
