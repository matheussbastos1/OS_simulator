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
    """Lifecycle states of a simulated process or thread."""
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    TERMINATED = "TERMINATED"

    # Aliases for Portuguese academic terms
    NOVO = "NEW"
    PRONTO = "READY"
    EXECUTANDO = "RUNNING"
    BLOQUEADO = "BLOCKED"
    CONCLUIDO = "TERMINATED"

    @classmethod
    def normalize(cls, state: "ProcessState") -> "ProcessState":
        """Normalize legacy WAITING alias to BLOCKED for Stage 5 state machine."""
        if state == cls.WAITING:
            return cls.BLOCKED
        return state

    @classmethod
    def from_string(cls, value: str) -> "ProcessState":
        """Parse string to ProcessState enum (supports English and Portuguese names)."""
        norm = value.strip().upper()
        mapping = {
            "NEW": cls.NEW,
            "NOVO": cls.NEW,
            "READY": cls.READY,
            "PRONTO": cls.READY,
            "RUNNING": cls.RUNNING,
            "EXECUTANDO": cls.RUNNING,
            "BLOCKED": cls.BLOCKED,
            "BLOQUEADO": cls.BLOCKED,
            "WAITING": cls.WAITING,
            "TERMINATED": cls.TERMINATED,
            "CONCLUIDO": cls.TERMINATED,
            "CONCLUÍDO": cls.TERMINATED,
        }
        if norm in mapping:
            return mapping[norm]
        raise ValueError(f"Estado de processo inválido: '{value}'")


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
    PROCESS_LIFECYCLE = "PROCESS_LIFECYCLE"
    SYSCALL_EXECUTED = "SYSCALL_EXECUTED"
    MUTEX_EVENT = "MUTEX_EVENT"
    DEADLOCK_DETECTED = "DEADLOCK_DETECTED"


class FileScanStatus(str, Enum):
    """Status classification for files in integrity / antivirus scans."""
    OK = "OK"
    OK_ENCRYPTED = "OK_ENCRYPTED"
    MODIFIED = "MODIFIED"
    SUSPICIOUS = "SUSPICIOUS"
    INACCESSIBLE = "INACCESSIBLE"


class SimulationEventType(str, Enum):
    """Discrete-event types processed by the Stage 5 simulation event loop."""
    PROCESS_TERMINATED = "PROCESS_TERMINATED"
    IO_COMPLETION = "IO_COMPLETION"
    MUTEX_WAKEUP = "MUTEX_WAKEUP"
    SLEEP_WAKEUP = "SLEEP_WAKEUP"
    PROCESS_ARRIVAL = "PROCESS_ARRIVAL"
    THREAD_ARRIVAL = "THREAD_ARRIVAL"
    QUANTUM_EXPIRE = "QUANTUM_EXPIRE"
    SYSCALL_REQUEST = "SYSCALL_REQUEST"
    DISPATCH_RESCHEDULE = "DISPATCH_RESCHEDULE"


class SyscallType(str, Enum):
    """Simulated system calls dispatched by threads during execution."""
    IO_READ = "IO_READ"
    IO_WRITE = "IO_WRITE"
    FS_READ = "FS_READ"
    FS_WRITE = "FS_WRITE"
    SLEEP_WAIT = "SLEEP_WAIT"
    YIELD = "YIELD"
    MUTEX_LOCK = "MUTEX_LOCK"
    MUTEX_UNLOCK = "MUTEX_UNLOCK"
    MEMORY_LOAD = "MEMORY_LOAD"
    MEMORY_WRITE = "MEMORY_WRITE"
    EXIT = "EXIT"

    @classmethod
    def from_string(cls, value: str) -> "SyscallType":
        """Parse string to SyscallType enum."""
        norm = value.strip().upper().replace("-", "_")
        if norm == "SLEEP":
            return cls.SLEEP_WAIT
        try:
            return cls(norm)
        except ValueError as exc:
            raise ValueError(f"Tipo de syscall inválido: '{value}'") from exc


class IOProfileType(str, Enum):
    """Thread I/O generation profile modes."""
    NONE = "NONE"
    FIXED = "FIXED"
    PERIODIC = "PERIODIC"
    RANDOM = "RANDOM"

    @classmethod
    def from_string(cls, value: str) -> "IOProfileType":
        """Parse string to IOProfileType enum."""
        norm = value.strip().upper()
        try:
            return cls(norm)
        except ValueError as exc:
            raise ValueError(f"Perfil de E/S inválido: '{value}'. Opções: none, fixed, periodic, random.") from exc


class BlockReason(str, Enum):
    """Reasons why a simulated thread transitions to BLOCKED."""
    NONE = "NONE"
    IO_WAIT = "IO_WAIT"
    FS_IO = "FS_IO"
    SLEEP_WAIT = "SLEEP_WAIT"
    MUTEX_WAIT = "MUTEX_WAIT"
