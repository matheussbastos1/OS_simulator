"""I/O Request model and operation status enums."""

from enum import Enum
import time
from typing import Optional


class IOOperationType(str, Enum):
    """Type of I/O operation."""
    READ = "READ"
    WRITE = "WRITE"


class IORequestStatus(str, Enum):
    """Lifecycle status of an I/O request."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IOPriority(str, Enum):
    """Priority level for I/O requests."""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class IORequest:
    """Represents an atomic I/O request in the simulation queue."""

    _counter: int = 1

    def __init__(
        self,
        operation: IOOperationType,
        block_id: int,
        track: Optional[int] = None,
        data: Optional[bytes | bytearray] = None,
        priority: IOPriority = IOPriority.NORMAL,
        request_id: Optional[int] = None,
        sectors_per_track: int = 4,
    ):
        if block_id < 0:
            raise ValueError(f"Endereço de bloco inválido: {block_id}. Deve ser >= 0.")
        if operation == IOOperationType.WRITE and data is None:
            raise ValueError("Operação de escrita requer payload de dados (data não pode ser None).")

        if request_id is not None:
            self.request_id = request_id
        else:
            self.request_id = IORequest._counter
            IORequest._counter += 1

        self.operation = operation
        self.block_id = block_id
        # If track is not explicitly specified, derive it logically from LBA geometry
        self.track = track if track is not None else (block_id // sectors_per_track)
        self.data: Optional[bytearray] = bytearray(data) if data is not None else None
        self.priority = priority
        self.status = IORequestStatus.PENDING
        self.result: Optional[bytearray] = None
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.completed_at: Optional[float] = None
        self.seek_distance: int = 0

    def mark_processing(self) -> None:
        """Transition request to PROCESSING status."""
        self.status = IORequestStatus.PROCESSING

    def mark_completed(self, result: Optional[bytearray | bytes] = None, seek_distance: int = 0) -> None:
        """Mark request as successfully completed with optional result data and seek distance."""
        self.status = IORequestStatus.COMPLETED
        self.completed_at = time.time()
        self.seek_distance = seek_distance
        if result is not None:
            self.result = bytearray(result)

    def mark_failed(self, error: str) -> None:
        """Mark request as failed with diagnostic error message."""
        self.status = IORequestStatus.FAILED
        self.completed_at = time.time()
        self.error_message = error

    def __repr__(self) -> str:
        return (
            f"<IORequest id={self.request_id} op={self.operation.value} "
            f"block={self.block_id} track={self.track} status={self.status.value}>"
        )
