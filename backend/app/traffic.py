"""Small, bounded admission budgets that never depend on database availability."""

from hashlib import sha256
from threading import Lock
from time import monotonic


class RequestBudget:
    """Limit expensive unauthenticated work before persistent rate-limit checks.

    This is a per-worker safety net. The reverse proxy supplies shared admission
    limits; database limits still govern accepted authentication transactions.
    """

    def __init__(self, *, per_address, total, seconds=60, max_addresses=2048, clock=monotonic):
        self.per_address, self.total = per_address, total
        self.seconds, self.max_addresses, self.clock = seconds, max_addresses, clock
        self._started = clock()
        self._counts = {}
        self._accepted = 0
        self._lock = Lock()

    def allow(self, address):
        # Fixed-size keys also bound memory if a WSGI caller supplies a bad address.
        key = sha256((address or "unknown").encode()).digest()
        with self._lock:
            now = self.clock()
            if now >= self._started + self.seconds:
                self._started, self._counts, self._accepted = now, {}, 0
            count = self._counts.get(key, 0)
            if (self._accepted >= self.total or count >= self.per_address
                    or (not count and len(self._counts) >= self.max_addresses)):
                return False
            self._counts[key] = count + 1
            self._accepted += 1
            return True
