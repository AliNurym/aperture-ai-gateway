"""Bounded throttling recovery without replacing a task authorization."""
import math
import time

import requests


def retry_throttled(operation, *, seconds=75, should_stop=None, on_retry=None):
    deadline, attempt = time.monotonic() + max(0, seconds), 0
    while True:
        if should_stop and should_stop():
            raise InterruptedError("Operation stopped while waiting for gateway capacity.")
        try:
            return operation()
        except requests.HTTPError as error:
            response = error.response
            if response is None or response.status_code != 429:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            try:
                pause = float(response.headers.get("Retry-After", ""))
            except (ValueError, TypeError):
                pause = min(10, 2 ** min(attempt, 4))
            if not math.isfinite(pause) or pause < 0:
                pause = 1
            pause = max(0.25, pause)
            if pause >= remaining:
                raise
            response.close()
            if on_retry:
                on_retry(pause)
            wake = time.monotonic() + pause
            while time.monotonic() < wake:
                if should_stop and should_stop():
                    raise InterruptedError("Operation stopped while waiting for gateway capacity.")
                time.sleep(min(0.25, max(0, wake - time.monotonic())))
            attempt += 1
