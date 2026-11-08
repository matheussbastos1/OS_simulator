"""Abstract ports and provisional adapters for OS Simulator."""

from abc import ABC, abstractmethod
from typing import List

from os_simulator.core.context import ExecutionContext


class BlockDevicePort(ABC):
    """Abstract port for block-level storage devices."""

    @abstractmethod
    def read_block(self, block_id: int) -> bytearray:
        """Read and return data from block_id."""
        raise NotImplementedError

    @abstractmethod
    def write_block(self, block_id: int, data: bytearray | bytes) -> None:
        """Write binary data to block_id."""
        raise NotImplementedError

    @abstractmethod
    def allocate_block(self) -> int:
        """Allocate a single free block and return its ID."""
        raise NotImplementedError

    @abstractmethod
    def allocate_blocks(self, count: int) -> List[int]:
        """Allocate 'count' free blocks and return their IDs."""
        raise NotImplementedError

    @abstractmethod
    def allocate_specific_blocks(self, block_ids: List[int]) -> List[int]:
        """Allocate specific block IDs.

        Raises DiskFullException or InvalidBlockException if any block
        is already allocated, damaged, or out of bounds.
        """
        raise NotImplementedError

    @abstractmethod
    def free_block(self, block_id: int) -> None:
        """Free previously allocated block."""
        raise NotImplementedError

    @abstractmethod
    def free_blocks(self, block_ids: List[int]) -> None:
        """Free a list of blocks."""
        raise NotImplementedError

    @abstractmethod
    def get_capacity(self) -> int:
        """Return total blocks capacity of the device."""
        raise NotImplementedError

    @abstractmethod
    def get_block_size(self) -> int:
        """Return block size in bytes."""
        raise NotImplementedError

    @abstractmethod
    def get_free_count(self) -> int:
        """Return count of currently free blocks."""
        raise NotImplementedError

    @abstractmethod
    def get_used_count(self) -> int:
        """Return count of currently allocated blocks."""
        raise NotImplementedError

    @abstractmethod
    def is_available(self, block_id: int) -> bool:
        """Check if block_id is within bounds and operational."""
        raise NotImplementedError

    @abstractmethod
    def is_block_free(self, block_id: int) -> bool:
        """Check if block_id is currently free for allocation."""
        raise NotImplementedError


class AuthorizationPort(ABC):
    """Abstract port for security and access authorization."""

    @abstractmethod
    def check_read(self, context: ExecutionContext, path: str) -> bool:
        """Verify read permission for resource."""
        raise NotImplementedError

    @abstractmethod
    def check_write(self, context: ExecutionContext, path: str) -> bool:
        """Verify write permission for resource."""
        raise NotImplementedError

    @abstractmethod
    def check_execute(self, context: ExecutionContext, path: str) -> bool:
        """Verify execute permission for resource."""
        raise NotImplementedError

    @abstractmethod
    def is_admin(self, context: ExecutionContext) -> bool:
        """Check administrative/kernel privileges."""
        raise NotImplementedError


class BootstrapSecurityPolicy(AuthorizationPort):
    """Provisional authorization policy for Stages 1 and 2.

    Allows operations under the initial execution context without requiring
    premature password storage or complex ACL engine implementations.
    """

    def check_read(self, context: ExecutionContext, path: str) -> bool:
        return True

    def check_write(self, context: ExecutionContext, path: str) -> bool:
        return True

    def check_execute(self, context: ExecutionContext, path: str) -> bool:
        return True

    def is_admin(self, context: ExecutionContext) -> bool:
        return context.is_root()
