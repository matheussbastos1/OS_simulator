"""Disk block data structures and storage abstractions."""

import hashlib
from typing import Optional

from os_simulator.core.ports import BlockDevicePort
from os_simulator.core.types import BlockStatus


class DiskBlock:
    """Represents a simulated physical disk block in Python memory."""

    def __init__(self, block_id: int, capacity: int = 4096):
        self.block_id = block_id
        self.capacity = capacity
        self.used_space = 0
        self.data: bytearray = bytearray(capacity)
        self.owner_inode: Optional[int] = None
        self.block_status: BlockStatus = BlockStatus.FREE
        self.next_block_id: Optional[int] = None

    @property
    def checksum(self) -> str:
        """Compute SHA-256 checksum of the used payload."""
        if self.used_space == 0:
            return ""
        return hashlib.sha256(self.data[:self.used_space]).hexdigest()

    def write(self, data: bytes | bytearray, owner_inode: Optional[int] = None) -> int:
        """Write binary data into block buffer up to capacity."""
        payload_size = len(data)
        if payload_size > self.capacity:
            raise ValueError(
                f"Tamanho dos dados ({payload_size} bytes) excede a capacidade do bloco ({self.capacity} bytes)."
            )
        # Clear buffer and copy payload
        self.data[:payload_size] = data
        if payload_size < self.capacity:
            self.data[payload_size:] = b"\x00" * (self.capacity - payload_size)
        self.used_space = payload_size
        self.block_status = BlockStatus.ALLOCATED
        if owner_inode is not None:
            self.owner_inode = owner_inode
        return payload_size

    def read(self) -> bytearray:
        """Read and return active data slice of the block."""
        return self.data[:self.used_space]

    def clear(self) -> None:
        """Reset block to clean free state."""
        self.data = bytearray(self.capacity)
        self.used_space = 0
        self.owner_inode = None
        self.block_status = BlockStatus.FREE
        self.next_block_id = None

    def __repr__(self) -> str:
        return (
            f"<DiskBlock id={self.block_id} status={self.block_status.value} "
            f"used={self.used_space}/{self.capacity} inode={self.owner_inode}>"
        )
