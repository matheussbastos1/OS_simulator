"""I/O Block Device Adapter connecting FileSystemService to IOManager and RAID."""

from typing import Dict, List, Optional

from os_simulator.core.exceptions import DiskFullException, InvalidBlockException
from os_simulator.core.ports import BlockDevicePort
from os_simulator.core.types import BlockStatus
from os_simulator.io.service import IOManager


class IOBlockDeviceAdapter(BlockDevicePort):
    """Adapter implementing BlockDevicePort over IOManager, schedulers, and RAID/SSD backends."""

    def __init__(
        self,
        io_manager: IOManager,
        logical_capacity: Optional[int] = None,
        block_size: int = 4096,
    ):
        self.io_manager = io_manager
        backend = io_manager.storage_backend

        # Derive logical capacity from backend if not explicitly given
        if logical_capacity is not None:
            self._capacity = logical_capacity
        elif hasattr(backend, "logical_capacity"):
            self._capacity = backend.logical_capacity
        elif hasattr(backend, "capacity_blocks"):
            self._capacity = backend.capacity_blocks
        elif hasattr(backend, "capacity"):
            self._capacity = backend.capacity
        else:
            self._capacity = 16

        self.block_size = block_size
        self._block_status: Dict[int, BlockStatus] = {
            i: BlockStatus.FREE for i in range(self._capacity)
        }

    def _validate_block_id(self, block_id: int) -> None:
        if not (0 <= block_id < self._capacity):
            raise InvalidBlockException(
                f"Endereço de bloco lógico {block_id} fora dos limites válidos [0, {self._capacity - 1}]."
            )

    def read_block(self, block_id: int) -> bytearray:
        """Route read request through IOManager."""
        self._validate_block_id(block_id)
        return self.io_manager.dispatch_read(block_id)

    def write_block(self, block_id: int, data: bytearray | bytes) -> None:
        """Route write request through IOManager."""
        self._validate_block_id(block_id)
        self.io_manager.dispatch_write(block_id, data)
        self._block_status[block_id] = BlockStatus.ALLOCATED

    def allocate_block(self) -> int:
        """Reserve first available logical block."""
        for b_id in range(self._capacity):
            if self._block_status[b_id] == BlockStatus.FREE:
                self._block_status[b_id] = BlockStatus.ALLOCATED
                return b_id
        raise DiskFullException("Dispositivo de E/S cheio. Nenhum bloco livre disponível.")

    def allocate_blocks(self, count: int) -> List[int]:
        """Reserve multiple logical blocks."""
        if count <= 0:
            return []
        free_ids = [b_id for b_id in range(self._capacity) if self._block_status[b_id] == BlockStatus.FREE]
        if len(free_ids) < count:
            raise DiskFullException(
                f"Espaço insuficiente: solicitados {count} blocos, disponíveis {len(free_ids)}."
            )
        allocated = free_ids[:count]
        for b_id in allocated:
            self._block_status[b_id] = BlockStatus.ALLOCATED
        return allocated

    def allocate_specific_blocks(self, block_ids: List[int]) -> List[int]:
        """Reserve specific logical blocks atomically."""
        if not block_ids:
            return []

        for b_id in block_ids:
            self._validate_block_id(b_id)
            if self._block_status[b_id] != BlockStatus.FREE:
                raise DiskFullException(f"Bloco {b_id} não está disponível para alocação.")

        for b_id in block_ids:
            self._block_status[b_id] = BlockStatus.ALLOCATED
        return block_ids

    def free_block(self, block_id: int) -> None:
        """Release logical block."""
        self._validate_block_id(block_id)
        self._block_status[block_id] = BlockStatus.FREE

    def free_blocks(self, block_ids: List[int]) -> None:
        """Release multiple logical blocks."""
        for b_id in block_ids:
            self.free_block(b_id)

    def get_capacity(self) -> int:
        return self._capacity

    def get_block_size(self) -> int:
        return self.block_size

    def get_free_count(self) -> int:
        return sum(1 for status in self._block_status.values() if status == BlockStatus.FREE)

    def get_used_count(self) -> int:
        return sum(1 for status in self._block_status.values() if status == BlockStatus.ALLOCATED)

    def is_available(self, block_id: int) -> bool:
        """Check logical bounds and underlying storage health."""
        if not (0 <= block_id < self._capacity):
            return False
        # If backend is a RAID controller, verify array is not in FAILED state
        backend = self.io_manager.storage_backend
        if hasattr(backend, "status"):
            # RAIDStatus.FAILED means array is unavailable
            from os_simulator.storage.raid import RAIDStatus
            if backend.status == RAIDStatus.FAILED:
                return False
        return True

    def is_block_free(self, block_id: int) -> bool:
        if not (0 <= block_id < self._capacity):
            return False
        return self._block_status[block_id] == BlockStatus.FREE
