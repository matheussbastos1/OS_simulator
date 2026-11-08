"""Storage allocation strategies: Contiguous, Linked FAT, and Indexed."""

from abc import ABC, abstractmethod
import math
import struct
from typing import Dict, List, Optional, Tuple

from os_simulator.core.exceptions import (
    DiskFragmentationException,
    DiskFullException,
    StorageException,
)
from os_simulator.core.ports import BlockDevicePort
from os_simulator.core.types import AllocationStrategy, BlockStatus
from os_simulator.filesystem.inode import Inode
from os_simulator.storage.block_device import DiskBlock


class AllocationStrategyBase(ABC):
    """Abstract base class for disk allocation strategies."""

    @abstractmethod
    def allocate(self, device: BlockDevicePort, inode: Inode, size_bytes: int) -> List[int]:
        """Allocate blocks necessary to hold size_bytes for inode and return allocated data block IDs."""
        raise NotImplementedError

    @abstractmethod
    def free(self, device: BlockDevicePort, inode: Inode) -> None:
        """Release all storage blocks (data and metadata) associated with inode."""
        raise NotImplementedError

    @abstractmethod
    def write_data(self, device: BlockDevicePort, inode: Inode, data: bytes | bytearray) -> None:
        """Write binary payload across allocated blocks according to strategy."""
        raise NotImplementedError

    @abstractmethod
    def read_data(self, device: BlockDevicePort, inode: Inode) -> bytearray:
        """Read and reassemble binary payload across allocated blocks according to strategy."""
        raise NotImplementedError


class ContiguousAllocation(AllocationStrategyBase):
    """Contiguous block allocation strategy (First-Fit / Best-Fit)."""

    def __init__(self, fit_policy: str = "first_fit"):
        self.fit_policy = fit_policy.lower()

    def _find_free_spans(self, device: BlockDevicePort) -> List[Tuple[int, int]]:
        """Find all contiguous sequences of free blocks as list of (start_block_id, length)."""
        spans: List[Tuple[int, int]] = []
        current_start: Optional[int] = None
        current_len = 0

        for block_id in range(device.get_capacity()):
            is_free = False
            # Check availability directly on device blocks
            if hasattr(device, "get_block"):
                block = getattr(device, "get_block")(block_id)
                is_free = block.block_status == BlockStatus.FREE
            else:
                is_free = device.is_available(block_id)

            if is_free:
                if current_start is None:
                    current_start = block_id
                    current_len = 1
                else:
                    current_len += 1
            else:
                if current_start is not None:
                    spans.append((current_start, current_len))
                    current_start = None
                    current_len = 0

        if current_start is not None:
            spans.append((current_start, current_len))

        return spans

    def allocate(self, device: BlockDevicePort, inode: Inode, size_bytes: int) -> List[int]:
        block_size = device.get_block_size()
        blocks_needed = math.ceil(size_bytes / block_size) if size_bytes > 0 else 0

        if blocks_needed == 0:
            inode.allocated_blocks = []
            inode.file_size = 0
            return []

        total_free = device.get_free_count()
        if total_free < blocks_needed:
            raise DiskFullException(
                f"Espaço insuficiente: necessários {blocks_needed} blocos, disponíveis {total_free}."
            )

        spans = self._find_free_spans(device)
        eligible_spans = [s for s in spans if s[1] >= blocks_needed]

        if not eligible_spans:
            max_contiguous = max((s[1] for s in spans), default=0)
            raise DiskFragmentationException(
                f"Fragmentação externa detectada: existem {total_free} blocos livres no total, "
                f"mas a maior sequência contígua é de apenas {max_contiguous} blocos "
                f"(necessários {blocks_needed} contíguos)."
            )

        if self.fit_policy == "best_fit":
            # Smallest span that fits
            chosen_span = min(eligible_spans, key=lambda s: s[1])
        else:
            # First span that fits
            chosen_span = eligible_spans[0]

        start_id = chosen_span[0]
        allocated = list(range(start_id, start_id + blocks_needed))

        for b_id in allocated:
            if hasattr(device, "get_block"):
                block = getattr(device, "get_block")(b_id)
                block.block_status = BlockStatus.ALLOCATED
                block.owner_inode = inode.inode_id

        inode.allocated_blocks = allocated
        inode.file_size = size_bytes
        inode.index_block_id = None
        inode.allocation_strategy = AllocationStrategy.CONTIGUOUS
        return allocated

    def free(self, device: BlockDevicePort, inode: Inode) -> None:
        if inode.allocated_blocks:
            device.free_blocks(inode.allocated_blocks)
            inode.allocated_blocks = []
        inode.file_size = 0

    def write_data(self, device: BlockDevicePort, inode: Inode, data: bytes | bytearray) -> None:
        block_size = device.get_block_size()
        payload_len = len(data)

        # Reallocate if size changed or blocks not yet allocated
        blocks_needed = math.ceil(payload_len / block_size) if payload_len > 0 else 0
        if len(inode.allocated_blocks) != blocks_needed:
            self.free(device, inode)
            if blocks_needed > 0:
                self.allocate(device, inode, payload_len)

        inode.file_size = payload_len
        for idx, block_id in enumerate(inode.allocated_blocks):
            start = idx * block_size
            end = min(start + block_size, payload_len)
            chunk = data[start:end]
            device.write_block(block_id, chunk)

    def read_data(self, device: BlockDevicePort, inode: Inode) -> bytearray:
        result = bytearray()
        bytes_left = inode.file_size

        for block_id in inode.allocated_blocks:
            if bytes_left <= 0:
                break
            block_data = device.read_block(block_id)
            read_size = min(len(block_data), bytes_left)
            result.extend(block_data[:read_size])
            bytes_left -= read_size

        return result


class LinkedFATAllocation(AllocationStrategyBase):
    """Linked File Allocation Table (FAT) strategy."""

    def __init__(self):
        # Maps block_id -> next_block_id (or -1 for EOF)
        self.fat_table: Dict[int, int] = {}

    def allocate(self, device: BlockDevicePort, inode: Inode, size_bytes: int) -> List[int]:
        block_size = device.get_block_size()
        blocks_needed = math.ceil(size_bytes / block_size) if size_bytes > 0 else 0

        if blocks_needed == 0:
            inode.allocated_blocks = []
            inode.file_size = 0
            return []

        allocated = device.allocate_blocks(blocks_needed, owner_inode=inode.inode_id)

        # Build FAT chain
        for i in range(len(allocated) - 1):
            self.fat_table[allocated[i]] = allocated[i + 1]
        self.fat_table[allocated[-1]] = -1  # EOF

        inode.allocated_blocks = allocated
        inode.file_size = size_bytes
        inode.index_block_id = None
        inode.allocation_strategy = AllocationStrategy.LINKED_FAT
        return allocated

    def free(self, device: BlockDevicePort, inode: Inode) -> None:
        if inode.allocated_blocks:
            for b_id in inode.allocated_blocks:
                self.fat_table.pop(b_id, None)
            device.free_blocks(inode.allocated_blocks)
            inode.allocated_blocks = []
        inode.file_size = 0

    def write_data(self, device: BlockDevicePort, inode: Inode, data: bytes | bytearray) -> None:
        block_size = device.get_block_size()
        payload_len = len(data)
        blocks_needed = math.ceil(payload_len / block_size) if payload_len > 0 else 0

        if len(inode.allocated_blocks) != blocks_needed:
            self.free(device, inode)
            if blocks_needed > 0:
                self.allocate(device, inode, payload_len)

        inode.file_size = payload_len
        current_block = inode.allocated_blocks[0] if inode.allocated_blocks else None
        offset = 0

        while current_block is not None and current_block != -1:
            end = min(offset + block_size, payload_len)
            chunk = data[offset:end]
            device.write_block(current_block, chunk)
            offset = end
            current_block = self.fat_table.get(current_block, -1)

    def read_data(self, device: BlockDevicePort, inode: Inode) -> bytearray:
        result = bytearray()
        if not inode.allocated_blocks:
            return result

        bytes_left = inode.file_size
        current_block = inode.allocated_blocks[0]

        while current_block is not None and current_block != -1 and bytes_left > 0:
            block_data = device.read_block(current_block)
            read_size = min(len(block_data), bytes_left)
            result.extend(block_data[:read_size])
            bytes_left -= read_size
            current_block = self.fat_table.get(current_block, -1)

        return result


class IndexedAllocation(AllocationStrategyBase):
    """Indexed allocation strategy with dedicated index block."""

    def allocate(self, device: BlockDevicePort, inode: Inode, size_bytes: int) -> List[int]:
        block_size = device.get_block_size()
        data_blocks_needed = math.ceil(size_bytes / block_size) if size_bytes > 0 else 0

        # Always allocate 1 index block + N data blocks
        total_blocks_needed = data_blocks_needed + 1
        if device.get_free_count() < total_blocks_needed:
            raise DiskFullException(
                f"Espaço insuficiente para alocação indexada: necessários {total_blocks_needed} "
                f"({data_blocks_needed} dados + 1 índice), disponíveis {device.get_free_count()}."
            )

        # 1. Allocate dedicated index block
        index_block_id = device.allocate_block(owner_inode=inode.inode_id)

        # 2. Allocate data blocks
        data_blocks = (
            device.allocate_blocks(data_blocks_needed, owner_inode=inode.inode_id)
            if data_blocks_needed > 0
            else []
        )

        # 3. Store block pointers in index block
        self._write_index_block(device, index_block_id, data_blocks)

        inode.index_block_id = index_block_id
        inode.allocated_blocks = data_blocks
        inode.file_size = size_bytes
        inode.allocation_strategy = AllocationStrategy.INDEXED
        return data_blocks

    def _write_index_block(self, device: BlockDevicePort, index_block_id: int, data_blocks: List[int]) -> None:
        """Encode list of data block IDs into index block binary payload."""
        encoded = struct.pack(f">{len(data_blocks)}I", *data_blocks)
        device.write_block(index_block_id, encoded)

    def _read_index_block(self, device: BlockDevicePort, index_block_id: int) -> List[int]:
        """Decode list of data block IDs from index block."""
        raw = device.read_block(index_block_id)
        if not raw:
            return []
        count = len(raw) // 4
        return list(struct.unpack(f">{count}I", raw[: count * 4]))

    def free(self, device: BlockDevicePort, inode: Inode) -> None:
        # Free data blocks
        if inode.allocated_blocks:
            device.free_blocks(inode.allocated_blocks)
            inode.allocated_blocks = []
        # Free index block
        if inode.index_block_id is not None:
            device.free_block(inode.index_block_id)
            inode.index_block_id = None
        inode.file_size = 0

    def write_data(self, device: BlockDevicePort, inode: Inode, data: bytes | bytearray) -> None:
        block_size = device.get_block_size()
        payload_len = len(data)
        data_blocks_needed = math.ceil(payload_len / block_size) if payload_len > 0 else 0

        # If block count changed, reallocate
        if len(inode.allocated_blocks) != data_blocks_needed or inode.index_block_id is None:
            self.free(device, inode)
            self.allocate(device, inode, payload_len)

        inode.file_size = payload_len
        # Write payload chunks to data blocks
        for idx, block_id in enumerate(inode.allocated_blocks):
            start = idx * block_size
            end = min(start + block_size, payload_len)
            chunk = data[start:end]
            device.write_block(block_id, chunk)

    def read_data(self, device: BlockDevicePort, inode: Inode) -> bytearray:
        result = bytearray()
        if inode.index_block_id is None or not inode.allocated_blocks:
            return result

        # Read pointers from index block to ensure structural integrity
        pointers = self._read_index_block(device, inode.index_block_id)
        bytes_left = inode.file_size

        for block_id in pointers:
            if bytes_left <= 0:
                break
            block_data = device.read_block(block_id)
            read_size = min(len(block_data), bytes_left)
            result.extend(block_data[:read_size])
            bytes_left -= read_size

        return result


class AllocationStrategyFactory:
    """Factory to retrieve allocation strategy handlers."""

    @staticmethod
    def get_strategy(strategy_type: AllocationStrategy) -> AllocationStrategyBase:
        if strategy_type == AllocationStrategy.CONTIGUOUS:
            return ContiguousAllocation()
        if strategy_type == AllocationStrategy.LINKED_FAT:
            return LinkedFATAllocation()
        if strategy_type == AllocationStrategy.INDEXED:
            return IndexedAllocation()
        raise ValueError(f"Estratégia de alocação não suportada: {strategy_type}")
