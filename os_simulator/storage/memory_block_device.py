"""In-memory block device adapter implementing BlockDevicePort (Stage 1)."""

from typing import List, Optional

from os_simulator.core.exceptions import DiskFullException, InvalidBlockException
from os_simulator.core.ports import BlockDevicePort
from os_simulator.core.types import BlockStatus
from os_simulator.storage.block_device import DiskBlock


class InMemoryBlockDevice(BlockDevicePort):
    """Simulated block storage device residing entirely in Python memory."""

    def __init__(self, capacity: int = 16, block_size: int = 4096):
        if capacity <= 0:
            raise ValueError("Capacidade do dispositivo deve ser maior que zero.")
        if block_size <= 0:
            raise ValueError("Tamanho do bloco deve ser maior que zero.")

        self.capacity = capacity
        self.block_size = block_size
        self.blocks: List[DiskBlock] = [
            DiskBlock(block_id=i, capacity=block_size) for i in range(capacity)
        ]

    def _validate_block_id(self, block_id: int) -> None:
        if not (0 <= block_id < self.capacity):
            raise InvalidBlockException(
                f"Endereço de bloco inválido: {block_id}. Limites válidos: [0, {self.capacity - 1}]."
            )

    def is_available(self, block_id: int) -> bool:
        """Check if block_id is within bounds and not marked BAD."""
        if not (0 <= block_id < self.capacity):
            return False
        return self.blocks[block_id].block_status != BlockStatus.BAD

    def get_block(self, block_id: int) -> DiskBlock:
        """Direct access to DiskBlock object (internal to storage layer)."""
        self._validate_block_id(block_id)
        return self.blocks[block_id]

    def read_block(self, block_id: int) -> bytearray:
        """Read active data from the specified block."""
        self._validate_block_id(block_id)
        return self.blocks[block_id].read()

    def write_block(self, block_id: int, data: bytearray | bytes, owner_inode: Optional[int] = None) -> None:
        """Write binary data to the specified block."""
        self._validate_block_id(block_id)
        self.blocks[block_id].write(data, owner_inode=owner_inode)

    def allocate_block(self, owner_inode: Optional[int] = None) -> int:
        """Find and allocate the first available free block."""
        for block in self.blocks:
            if block.block_status == BlockStatus.FREE:
                block.block_status = BlockStatus.ALLOCATED
                block.owner_inode = owner_inode
                return block.block_id
        raise DiskFullException("Disco simulado cheio. Nenhum bloco livre disponível.")

    def allocate_blocks(self, count: int, owner_inode: Optional[int] = None) -> List[int]:
        """Allocate 'count' free blocks. Roll back if insufficient space."""
        if count <= 0:
            return []
        free_blocks = [b.block_id for b in self.blocks if b.block_status == BlockStatus.FREE]
        if len(free_blocks) < count:
            raise DiskFullException(
                f"Espaço insuficiente: solicitados {count} blocos, disponíveis {len(free_blocks)}."
            )
        allocated: List[int] = []
        for block_id in free_blocks[:count]:
            self.blocks[block_id].block_status = BlockStatus.ALLOCATED
            self.blocks[block_id].owner_inode = owner_inode
            allocated.append(block_id)
        return allocated

    def free_block(self, block_id: int) -> None:
        """Release allocated block back to free pool."""
        self._validate_block_id(block_id)
        self.blocks[block_id].clear()

    def free_blocks(self, block_ids: List[int]) -> None:
        """Release multiple blocks."""
        for b_id in block_ids:
            self.free_block(b_id)

    def get_capacity(self) -> int:
        """Return total blocks capacity."""
        return self.capacity

    def get_block_size(self) -> int:
        """Return block size in bytes."""
        return self.block_size

    def get_free_count(self) -> int:
        """Count how many blocks are currently FREE."""
        return sum(1 for b in self.blocks if b.block_status == BlockStatus.FREE)

    def get_used_count(self) -> int:
        """Count how many blocks are currently ALLOCATED."""
        return sum(1 for b in self.blocks if b.block_status == BlockStatus.ALLOCATED)

    def get_total_bytes(self) -> int:
        """Total storage capacity in bytes."""
        return self.capacity * self.block_size
