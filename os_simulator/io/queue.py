"""I/O Request Queue for managing scheduled and pending operations."""

from typing import List, Optional

from os_simulator.io.request import IORequest, IORequestStatus


class IOQueue:
    """Queue holding I/O requests waiting for dispatch by disk schedulers."""

    def __init__(self, max_size: Optional[int] = None):
        self.max_size = max_size
        self._requests: List[IORequest] = []
        self._history: List[IORequest] = []

    def enqueue(self, request: IORequest) -> None:
        """Add an I/O request to the pending queue."""
        if self.max_size is not None and len(self._requests) >= self.max_size:
            raise OverflowError(f"Fila de E/S cheia (limite: {self.max_size} requisições).")

        self._requests.append(request)

    def dequeue(self) -> Optional[IORequest]:
        """Remove and return the next request in FIFO order."""
        if not self._requests:
            return None
        req = self._requests.pop(0)
        self._history.append(req)
        return req

    def remove(self, request: IORequest) -> bool:
        """Remove a specific request from the pending queue."""
        if request in self._requests:
            self._requests.remove(request)
            self._history.append(request)
            return True
        return False

    def peek(self) -> Optional[IORequest]:
        """Inspect the head of the queue without removing it."""
        return self._requests[0] if self._requests else None

    def is_empty(self) -> bool:
        """Check if there are no pending requests."""
        return len(self._requests) == 0

    def get_pending_requests(self) -> List[IORequest]:
        """Return shallow copy of all pending requests."""
        return list(self._requests)

    def get_completed_requests(self) -> List[IORequest]:
        """Return all historical requests marked COMPLETED."""
        return [r for r in self._history if r.status == IORequestStatus.COMPLETED]

    def get_failed_requests(self) -> List[IORequest]:
        """Return all historical requests marked FAILED."""
        return [r for r in self._history if r.status == IORequestStatus.FAILED]

    def clear(self) -> None:
        """Reset queue and history."""
        self._requests.clear()
        self._history.clear()

    def __len__(self) -> int:
        return len(self._requests)

    def __repr__(self) -> str:
        return f"<IOQueue pending={len(self._requests)} history={len(self._history)}>"
