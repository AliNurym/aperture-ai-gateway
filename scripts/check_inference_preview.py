"""Exercise the combined inference and CPU preview using a local SSE fixture.

The fixture verifies protocol integration only. It is not a model-quality test,
does not contact an upstream provider, and does not make Solana payments.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "scripts" / "inference_preview.py"
FIXTURE_MODEL = "aperture-integration-fixture"
FIXTURE_TEXT = "A computer follows instructions."


class ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.server.requests.append({"request": request, "authorization": self.headers.get("Authorization")})
        if request.get("model") != FIXTURE_MODEL or request.get("stream") is not True:
            self.send_error(422)
            return

        events = [
            {"model": FIXTURE_MODEL, "choices": [{"index": 0, "delta": {"content": FIXTURE_TEXT}}]},
            "[DONE]",
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for event in events:
                data = event if isinstance(event, str) else json.dumps(event, separators=(",", ":"))
                self.wfile.write(("data: " + data + "\n\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    state_root = ROOT / ".aperture" / "integration-checks"
    state_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    server.daemon_threads = True
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="inference-preview-", dir=state_root) as temporary:
            state = Path(temporary)
            command = [sys.executable, str(PREVIEW), "--check",
                       "--base-url", f"http://127.0.0.1:{server.server_port}/v1",
                       "--model", FIXTURE_MODEL, "--state", str(state)]
            result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8",
                                    capture_output=True, timeout=240, check=False)
            if result.stdout:
                print(result.stdout, end="", flush=True)
            if result.returncode:
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="", flush=True)
                raise RuntimeError(f"Combined preview exited with status {result.returncode}.")

            evidence = json.loads((state / "evidence.json").read_text(encoding="utf-8"))
            if (evidence.get("model_quality") != "not_evaluated"
                    or evidence.get("upstream_model_billing") != "outside_aperture"
                    or evidence.get("worker_settlement_share_pct") != 100
                    or evidence.get("devnet_settlement") != "not_exercised"):
                raise RuntimeError("Combined preview evidence does not preserve the product's settlement boundaries.")
            if (evidence.get("duplicate_admission") != "same_task"
                    or evidence.get("fresh_client_recovery") != "same_output"
                    or evidence.get("revoked_agent_quote") != "rejected_403"
                    or evidence.get("cpu_output", "").strip() != "42"
                    or evidence.get("receipt", {}).get("execution_status") != "completed"
                    or evidence.get("receipt", {}).get("settlement_type") != "OFF_CHAIN"):
                raise RuntimeError("Combined preview did not verify its expected task lifecycle and CPU result.")
            model_output = evidence.get("output", "").split("[Aperture inference metadata]")[0].strip()
            if model_output != FIXTURE_TEXT:
                raise RuntimeError("The configured endpoint response did not reach the verified task result.")

        if len(server.requests) != 1:
            raise RuntimeError(f"Expected exactly one model endpoint request; observed {len(server.requests)}.")
        sent = server.requests[0]
        messages = sent["request"].get("messages", [])
        if (sent["authorization"] is not None
                or not any(message.get("role") == "user"
                           and "what is a computer" in message.get("content", "").lower()
                           for message in messages)):
            raise RuntimeError("The local fixture received unexpected credentials or an invalid request.")
        print("Local provider fixture: one streamed request; synthetic response; model quality not evaluated.")
        print("Combined inference + CPU preview: passed; OFF_CHAIN; no upstream provider or Solana request.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Combined inference preview check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
