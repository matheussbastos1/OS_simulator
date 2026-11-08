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
from os_simulator.core.types import AllocationStrategy
from os_simulator.filesystem.inode import Inode


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

    def _find_free_spans(
        self, device: BlockDevicePort, excluded_blocks: Optional[set] = None
    ) -> List[Tuple[int, int]]:
        """Find all contiguous sequences of free blocks as list of (start_block_id, length).

        If excluded_blocks is provided, blocks in that set are considered free for planning.
        """
        spans: List[Tuple[int, int]] = []
        current_start: Optional[int] = None
        current_len = 0
        excluded = excluded_blocks or set()

        for block_id in range(device.get_capacity()):
            is_free = device.is_block_free(block_id) or (block_id in excluded)

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
            chosen_span = min(eligible_spans, key=lambda s: s[1])
        else:
            chosen_span = eligible_spans[0]

        start_id = chosen_span[0]
        allocated = list(range(start_id, start_id + blocks_needed))

        # Allocate via formal BlockDevicePort method
        device.allocate_specific_blocks(allocated)

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
        blocks_needed = math.ceil(payload_len / block_size) if payload_len > 0 else 0
        current_blocks = list(inode.allocated_blocks)
        current_count = len(current_blocks)
        old_size = inode.file_size

        # Case 1: Empty file write
        if blocks_needed == 0:
            self.free(device, inode)
            inode.file_size = 0
            return

        # Case 2: In-place overwrite (exact same number of blocks)
        if blocks_needed == current_count:
            inode.file_size = payload_len
            for idx, block_id in enumerate(current_blocks):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])
            return

        # Case 3: Shrinking (fewer blocks needed)
        if blocks_needed < current_count:
            kept_blocks = current_blocks[:blocks_needed]
            excess_blocks = current_blocks[blocks_needed:]

            # Write payload to kept blocks
            for idx, block_id in enumerate(kept_blocks):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])

            # Free excess blocks
            device.free_blocks(excess_blocks)
            inode.allocated_blocks = kept_blocks
            inode.file_size = payload_len
            return

        # Case 4: Growing (more blocks needed)
        delta = blocks_needed - current_count

        # 4a. Try in-place expansion if immediately subsequent blocks are free
        if current_count > 0:
            last_block = current_blocks[-1]
            expansion_candidate = list(range(last_block + 1, last_block + 1 + delta))
            can_expand_in_place = all(
                b < device.get_capacity() and device.is_block_free(b)
                for b in expansion_candidate
            )
            if can_expand_in_place:
                device.allocate_specific_blocks(expansion_candidate)
                combined = current_blocks + expansion_candidate
                for idx, block_id in enumerate(combined):
                    start = idx * block_size
                    end = min(start + block_size, payload_len)
                    device.write_block(block_id, data[start:end])
                inode.allocated_blocks = combined
                inode.file_size = payload_len
                return

        # 4b. Expansion in-place not possible; check if a new span exists in current free space
        spans = self._find_free_spans(device)
        eligible_spans = [s for s in spans if s[1] >= blocks_needed]
        if eligible_spans:
            chosen = min(eligible_spans, key=lambda s: s[1]) if self.fit_policy == "best_fit" else eligible_spans[0]
            new_span = list(range(chosen[0], chosen[0] + blocks_needed))
            device.allocate_specific_blocks(new_span)
            for idx, block_id in enumerate(new_span):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])
            if current_blocks:
                device.free_blocks(current_blocks)
            inode.allocated_blocks = new_span
            inode.file_size = payload_len
            return

        # 4c. New span not available in current free space.
        # Check whether freeing current blocks would allow reallocation
        total_available = device.get_free_count() + current_count
        if total_available < blocks_needed:
            raise DiskFullException(
                f"Espaço insuficiente: necessários {blocks_needed} blocos, disponíveis {total_available}."
            )

        # Plan with current blocks treated as free
        planned_spans = self._find_free_spans(device, excluded_blocks=set(current_blocks))
        eligible_planned = [s for s in planned_spans if s[1] >= blocks_needed]
        if not eligible_planned:
            max_contiguous = max((s[1] for s in planned_spans), default=0)
            raise DiskFragmentationException(
                f"Fragmentação externa detectada: existem {total_available} blocos potencialmente livres, "
                f"mas a maior sequência contígua possível é de apenas {max_contiguous} blocos "
                f"(necessários {blocks_needed} contíguos)."
            )

        # Reallocation with transactional rollback
        old_data = self.read_data(device, inode) if current_blocks else bytearray()
        device.free_blocks(current_blocks)
        try:
            new_allocated = self.allocate(device, inode, payload_len)
            for idx, block_id in enumerate(new_allocated):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])
            inode.allocated_blocks = new_allocated
            inode.file_size = payload_len
        except Exception:
            # Rollback: restore previous state
            if inode.allocated_blocks:
                device.free_blocks(inode.allocated_blocks)
            device.allocate_specific_blocks(current_blocks)
            if old_data:
                for idx, block_id in enumerate(current_blocks):
                    start = idx * block_size
                    end = min(start + block_size, len(old_data))
                    device.write_block(block_id, old_data[start:end])
            inode.allocated_blocks = current_blocks
            inode.file_size = old_size
            raise

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

        allocated = device.allocate_blocks(blocks_needed)

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
        current_blocks = list(inode.allocated_blocks)
        current_count = len(current_blocks)
        old_size = inode.file_size

        # Case 1: Empty file write
        if blocks_needed == 0:
            self.free(device, inode)
            inode.file_size = 0
            return

        # Case 2: In-place overwrite (same number of blocks)
        if blocks_needed == current_count:
            inode.file_size = payload_len
            offset = 0
            curr = current_blocks[0]
            while curr != -1 and offset < payload_len:
                end = min(offset + block_size, payload_len)
                device.write_block(curr, data[offset:end])
                offset = end
                curr = self.fat_table.get(curr, -1)
            return

        # Case 3: Shrinking (fewer blocks needed)
        if blocks_needed < current_count:
            kept_blocks = current_blocks[:blocks_needed]
            excess_blocks = current_blocks[blocks_needed:]

            # Update FAT table
            self.fat_table[kept_blocks[-1]] = -1
            for b_id in excess_blocks:
                self.fat_table.pop(b_id, None)

            # Free excess blocks on device
            device.free_blocks(excess_blocks)

            # Write data to kept blocks
            offset = 0
            curr = kept_blocks[0]
            while curr != -1 and offset < payload_len:
                end = min(offset + block_size, payload_len)
                device.write_block(curr, data[offset:end])
                offset = end
                curr = self.fat_table.get(curr, -1)

            inode.allocated_blocks = kept_blocks
            inode.file_size = payload_len
            return

        # Case 4: Growing (more blocks needed)
        delta = blocks_needed - current_count
        if device.get_free_count() < delta:
            raise DiskFullException(
                f"Espaço insuficiente: necessários {delta} blocos adicionais, disponíveis {device.get_free_count()}."
            )

        if current_count == 0:
            # Fresh allocation
            new_blocks = self.allocate(device, inode, payload_len)
            offset = 0
            curr = new_blocks[0]
            while curr != -1 and offset < payload_len:
                end = min(offset + block_size, payload_len)
                device.write_block(curr, data[offset:end])
                offset = end
                curr = self.fat_table.get(curr, -1)
            return

        # Allocate additional blocks and link to existing chain
        new_blocks = device.allocate_blocks(delta)
        try:
            self.fat_table[current_blocks[-1]] = new_blocks[0]
            for i in range(len(new_blocks) - 1):
                self.fat_table[new_blocks[i]] = new_blocks[i + 1]
            self.fat_table[new_blocks[-1]] = -1

            combined = current_blocks + new_blocks
            offset = 0
            curr = combined[0]
            while curr != -1 and offset < payload_len:
                end = min(offset + block_size, payload_len)
                device.write_block(curr, data[offset:end])
                offset = end
                curr = self.fat_table.get(curr, -1)

            inode.allocated_blocks = combined
            inode.file_size = payload_len
        except Exception:
            # Rollback added blocks
            for b_id in new_blocks:
                self.fat_table.pop(b_id, None)
            self.fat_table[current_blocks[-1]] = -1
            device.free_blocks(new_blocks)
            inode.allocated_blocks = current_blocks
            inode.file_size = old_size
            raise

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

        total_blocks_needed = data_blocks_needed + 1
        if device.get_free_count() < total_blocks_needed:
            raise DiskFullException(
                f"Espaço insuficiente para alocação indexada: necessários {total_blocks_needed} "
                f"({data_blocks_needed} dados + 1 índice), disponíveis {device.get_free_count()}."
            )

        # 1. Allocate dedicated index block
        index_block_id = device.allocate_block()

        # 2. Allocate data blocks
        data_blocks = (
            device.allocate_blocks(data_blocks_needed)
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
        if inode.allocated_blocks:
            device.free_blocks(inode.allocated_blocks)
            inode.allocated_blocks = []
        if inode.index_block_id is not None:
            device.free_block(inode.index_block_id)
            inode.index_block_id = None
        inode.file_size = 0

    def write_data(self, device: BlockDevicePort, inode: Inode, data: bytes | bytearray) -> None:
        block_size = device.get_block_size()
        payload_len = len(data)
        data_blocks_needed = math.ceil(payload_len / block_size) if payload_len > 0 else 0
        current_blocks = list(inode.allocated_blocks)
        current_count = len(current_blocks)
        old_size = inode.file_size

        # Case 1: Empty file write
        if data_blocks_needed == 0:
            self.free(device, inode)
            inode.file_size = 0
            return

        # Case 2: Fresh allocation (file had no index block yet)
        if inode.index_block_id is None:
            self.allocate(device, inode, payload_len)
            for idx, block_id in enumerate(inode.allocated_blocks):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])
            return

        # Case 3: In-place overwrite (exact same number of data blocks)
        if data_blocks_needed == current_count:
            inode.file_size = payload_len
            for idx, block_id in enumerate(current_blocks):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])
            return

        # Case 4: Shrinking (fewer data blocks needed)
        if data_blocks_needed < current_count:
            kept_blocks = current_blocks[:data_blocks_needed]
            excess_blocks = current_blocks[data_blocks_needed:]

            # Write payload to kept blocks
            for idx, block_id in enumerate(kept_blocks):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])

            # Update index block pointers
            self._write_index_block(device, inode.index_block_id, kept_blocks)

            # Free excess blocks on device
            device.free_blocks(excess_blocks)
            inode.allocated_blocks = kept_blocks
            inode.file_size = payload_len
            return

        # Case 5: Growing (more data blocks needed)
        delta = data_blocks_needed - current_count
        if device.get_free_count() < delta:
            raise DiskFullException(
                f"Espaço insuficiente: necessários {delta} blocos adicionais, disponíveis {device.get_free_count()}."
            )

        new_blocks = device.allocate_blocks(delta)
        try:
            combined = current_blocks + new_blocks
            self._write_index_block(device, inode.index_block_id, combined)
            for idx, block_id in enumerate(combined):
                start = idx * block_size
                end = min(start + block_size, payload_len)
                device.write_block(block_id, data[start:end])
            inode.allocated_blocks = combined
            inode.file_size = payload_len
        except Exception:
            # Rollback: release newly allocated blocks and restore index pointers
            device.free_blocks(new_blocks)
            self._write_index_block(device, inode.index_block_id, current_blocks)
            inode.allocated_blocks = current_blocks
            inode.file_size = old_size
            raise

    def read_data(self, device: BlockDevicePort, inode: Inode) -> bytearray:
        result = bytearray()
        if inode.index_block_id is None or not inode.allocated_blocks:
            return result

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
