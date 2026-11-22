"""Global type definitions, enums, and constants for OS Simulator."""

from enum import Enum


class NodeType(str, Enum):
    """File system node types."""
    DIRECTORY = "DIRECTORY"
    FILE = "FILE"


class AllocationStrategy(str, Enum):
    """Disk storage allocation strategies."""
    CONTIGUOUS = "CONTIGUOUS"
    LINKED_FAT = "LINKED_FAT"
    INDEXED = "INDEXED"

    @classmethod
    def from_string(cls, value: str) -> "AllocationStrategy":
        """Parse string to allocation strategy enum."""
        normalized = value.strip().upper()
        if normalized in ("CONTIGUOUS", "CONTIGUA", "CONTÍGUA"):
            return cls.CONTIGUOUS
        if normalized in ("FAT", "LINKED", "LINKED_FAT", "ENCADEADA"):
            return cls.LINKED_FAT
        if normalized in ("INDEXED", "INDEXADA", "INODE"):
            return cls.INDEXED
        raise ValueError(f"Estratégia de alocação inválida: '{value}'")


class BlockStatus(str, Enum):
    """Physical block allocation status."""
    FREE = "FREE"
    ALLOCATED = "ALLOCATED"
    BAD = "BAD"
    PARITY = "PARITY"


class PrivilegeMode(str, Enum):
    """Execution ring / privilege modes."""
    KERNEL_MODE = "KERNEL_MODE"
    USER_MODE = "USER_MODE"

    # Aliases for Portuguese academic terms
    MODO_KERNEL = "KERNEL_MODE"
    MODO_USUARIO = "USER_MODE"


class ProcessType(str, Enum):
    """Process priority / allocation type."""
    CRITICAL = "CRITICAL"
    NORMAL = "NORMAL"


class ProcessState(str, Enum):
    """Lifecycle states of a simulated process."""
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    TERMINATED = "TERMINATED"


class SegmentStatus(str, Enum):
    """Allocation status of a reserved memory segment."""
    FREE = "FREE"
    ALLOCATED = "ALLOCATED"


class PageOrigin(str, Enum):
    """Valid provenance/origin of a logical page on page fault resolution."""
    PROCESS_IMAGE = "PROCESS_IMAGE"
    ZERO_FILL_ON_DEMAND = "ZERO_FILL_ON_DEMAND"
    SWAP_STORAGE = "SWAP_STORAGE"


class ReplacementAlgorithm(str, Enum):
    """Page replacement algorithm policies."""
    LRU = "LRU"
    SECOND_CHANCE = "SECOND_CHANCE"

    @classmethod
    def from_string(cls, value: str) -> "ReplacementAlgorithm":
        """Parse string to replacement algorithm enum."""
        norm = value.strip().upper().replace("-", "_").replace(" ", "_")
        if norm in ("LRU", "LEAST_RECENTLY_USED"):
            return cls.LRU
        if norm in ("SECOND_CHANCE", "SEGUNDA_CHANCE", "CLOCK"):
            return cls.SECOND_CHANCE
        raise ValueError(f"Algoritmo de substituição inválido: '{value}'. Opções: LRU, SECOND_CHANCE.")



class AuditEventType(str, Enum):
    """Types of security events recorded in the audit log."""
    ACCESS_GRANTED = "ACCESS_GRANTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    PRIVILEGE_ELEVATION = "PRIVILEGE_ELEVATION"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    OWNERSHIP_CHANGED = "OWNERSHIP_CHANGED"
    USER_MANAGEMENT = "USER_MANAGEMENT"
    TAMPER_DETECTED = "TAMPER_DETECTED"
    CRYPTO_OPERATION = "CRYPTO_OPERATION"


class FileScanStatus(str, Enum):
    """Status classification for files in integrity / antivirus scans."""
    OK = "OK"
    OK_ENCRYPTED = "OK_ENCRYPTED"
    MODIFIED = "MODIFIED"
    SUSPICIOUS = "SUSPICIOUS"
    INACCESSIBLE = "INACCESSIBLE"
