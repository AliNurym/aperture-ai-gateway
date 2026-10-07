#!/usr/bin/env python3
"""Check local gateway readiness and open the Aperture presentation preview."""

import json
import sys
import urllib.request
import webbrowser


GATEWAY_URL = "http://127.0.0.1:8000"
CONSOLE_URL = "http://127.0.0.1:3000"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Aperture presentation preview")
    print("Checking the local gateway health endpoint...")
    request = urllib.request.Request(
        GATEWAY_URL + "/health",
        headers={"User-Agent": "AperturePitchPreview/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        print("Gateway is unavailable at " + GATEWAY_URL + ": " + str(error))
        print("Start the local workspace with start_preview.bat, then try again.")
        raise SystemExit(1) from error

    print("Gateway status: " + str(health.get("status", "unknown")))
    print("Network: " + str(health.get("network", "unknown")))
    print("Active workers reported: " + str(health.get("active_worker_count", "unknown")))
    if health.get("status") != "ready":
        print("The gateway does not currently report an active ready worker.")
        print("Start or reconnect a worker before running a real task in Compute Studio.")
        raise SystemExit(1)

    print("Opening the console at " + CONSOLE_URL)
    print("The overview simulator uses illustrative values and does not submit or execute a task.")
    if not webbrowser.open(CONSOLE_URL):
        print("The browser did not open automatically. Open " + CONSOLE_URL + " manually.")


if __name__ == "__main__":
    main()
