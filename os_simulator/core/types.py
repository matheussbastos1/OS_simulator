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


class ProcessType(str, Enum):
    """Process priority / allocation type."""
    CRITICAL = "CRITICAL"
    NORMAL = "NORMAL"
