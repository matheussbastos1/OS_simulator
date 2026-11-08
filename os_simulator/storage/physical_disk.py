"""Physical Disk simulation with tracks, sectors, and failure simulation."""

from typing import List, Optional

from os_simulator.core.exceptions import DiskFullException, InvalidBlockException, StorageException
from os_simulator.core.types import BlockStatus
from os_simulator.storage.block_device import DiskBlock


class DiskFailureException(StorageException):
    """Raised when an operation is attempted on a failed physical disk."""
    pass


class PhysicalDisk:
    """Represents a physical hard disk or array member disk."""

    def __init__(
        self,
        disk_id: int,
        capacity_blocks: int = 16,
        block_size: int = 4096,
        sectors_per_track: int = 4,
    ):
        if capacity_blocks <= 0:
            raise ValueError("Capacidade em blocos deve ser > 0.")
        if block_size <= 0:
            raise ValueError("Tamanho do bloco deve ser > 0.")
        if sectors_per_track <= 0:
            raise ValueError("Setores por trilha deve ser > 0.")

        self.disk_id = disk_id
        self.capacity_blocks = capacity_blocks
        self.block_size = block_size
        self.sectors_per_track = sectors_per_track
        self.total_tracks = (capacity_blocks + sectors_per_track - 1) // sectors_per_track

        self.blocks: List[DiskBlock] = [
            DiskBlock(block_id=i, capacity=block_size) for i in range(capacity_blocks)
        ]
        self.is_online: bool = True
        self.read_count: int = 0
        self.write_count: int = 0

    def fail(self) -> None:
        """Simulate hardware failure of the physical disk."""
        self.is_online = False

    def recover(self) -> None:
        """Restore disk to online state."""
        self.is_online = True

    def _validate_online(self) -> None:
        if not self.is_online:
            raise DiskFailureException(
                f"Disco físico {self.disk_id} está FALHO (offline). Operação rejeitada."
            )

    def _validate_block_id(self, block_id: int) -> None:
        if not (0 <= block_id < self.capacity_blocks):
            raise InvalidBlockException(
                f"Endereço de bloco {block_id} fora dos limites do disco físico {self.disk_id} [0, {self.capacity_blocks - 1}]."
            )

    def get_track_for_block(self, block_id: int) -> int:
        """Translate physical block ID to cylinder/track index."""
        self._validate_block_id(block_id)
        return block_id // self.sectors_per_track

    def read_block(self, block_id: int) -> bytearray:
        """Read data from physical block."""
        self._validate_online()
        self._validate_block_id(block_id)
        self.read_count += 1
        return self.blocks[block_id].read()

    def write_block(self, block_id: int, data: bytes | bytearray, is_parity: bool = False) -> None:
        """Write data to physical block."""
        self._validate_online()
        self._validate_block_id(block_id)
        self.write_count += 1
        self.blocks[block_id].write(data)
        if is_parity:
            self.blocks[block_id].block_status = BlockStatus.PARITY

    def is_block_free(self, block_id: int) -> bool:
        """Check if block is available."""
        self._validate_block_id(block_id)
        return self.blocks[block_id].block_status == BlockStatus.FREE

    def free_block(self, block_id: int) -> None:
        """Clear block content."""
        self._validate_online()
        self._validate_block_id(block_id)
        self.blocks[block_id].clear()

    def __repr__(self) -> str:
        state = "ONLINE" if self.is_online else "FAILED"
        return f"<PhysicalDisk id={self.disk_id} state={state} blocks={self.capacity_blocks}>"
