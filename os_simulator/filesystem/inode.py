"""Inode metadata structure and POSIX attribute tracking."""

import time
from typing import List, Optional

from os_simulator.core.types import AllocationStrategy, NodeType


class Inode:
    """Centralizes POSIX metadata, block mapping, and allocation strategy for a file or directory."""

    def __init__(
        self,
        inode_id: int,
        node_type: NodeType = NodeType.FILE,
        file_size: int = 0,
        owner: str = "root",
        group: str = "root",
        permissions: str = "755",
        allocation_strategy: AllocationStrategy = AllocationStrategy.INDEXED,
    ):
        self.inode_id = inode_id
        self.node_type = node_type
        self.file_size = file_size
        self.owner = owner
        self.group = group
        self.permissions = permissions
        self.allocation_strategy = allocation_strategy
        self.allocated_blocks: List[int] = []
        self.index_block_id: Optional[int] = None
        self.is_encrypted: bool = False
        self.integrity_hash: Optional[str] = None
        self.created_at = time.time()
        self.modified_at = self.created_at

    def get_data_block_count(self) -> int:
        """Return total number of data blocks assigned to this file."""
        return len(self.allocated_blocks)

    def get_total_allocated_blocks(self) -> int:
        """Return data blocks plus index block if applicable."""
        count = len(self.allocated_blocks)
        if self.index_block_id is not None:
            count += 1
        return count

    def get_allocated_data_bytes(self, block_size: int = 4096) -> int:
        """Return total bytes allocated for data payload."""
        return len(self.allocated_blocks) * block_size

    def get_internal_fragmentation(self, block_size: int = 4096) -> int:
        """Calculate wasted bytes in the last data block."""
        if not self.allocated_blocks or self.file_size == 0:
            return 0
        allocated_bytes = len(self.allocated_blocks) * block_size
        return max(0, allocated_bytes - self.file_size)

    def __repr__(self) -> str:
        return (
            f"<Inode id={self.inode_id} type={self.node_type.value} size={self.file_size}B "
            f"blocks={self.allocated_blocks} strategy={self.allocation_strategy.value}>"
        )
