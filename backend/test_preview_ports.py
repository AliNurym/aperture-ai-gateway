import socket
import unittest

from preview_ports import resolve_preview_port


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class PreviewPortTests(unittest.TestCase):
    def test_uses_a_free_default_without_reallocation(self):
        port, changed = resolve_preview_port(None, find_free_port(), "api-port", find_free_port)
        self.assertFalse(changed)
        self.assertGreaterEqual(port, 1)

    def test_busy_default_uses_a_free_fallback(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            occupied = listener.getsockname()[1]
            port, changed = resolve_preview_port(None, occupied, "api-port", find_free_port)
        self.assertTrue(changed)
        self.assertNotEqual(port, occupied)

    def test_explicit_busy_port_fails_with_actionable_error(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            occupied = listener.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "Choose a free port or omit --api-port"):
                resolve_preview_port(occupied, 8000, "api-port", find_free_port)

    def test_fallback_does_not_reuse_the_other_preview_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            occupied = listener.getsockname()[1]
            values = iter((occupied, find_free_port()))
            port, changed = resolve_preview_port(None, occupied, "ui-port", lambda: next(values), excluded=(occupied,))
        self.assertTrue(changed)
        self.assertNotEqual(port, occupied)


if __name__ == "__main__":
    unittest.main()
