"""Sliding compaction algorithm for reserved memory defragmentation."""

from typing import Any, Dict, List, Tuple

from os_simulator.core.types import SegmentStatus
from os_simulator.memory.segment import MemorySegment, ReservedMemoryManager


def compact_reserved_memory(reserved_manager: ReservedMemoryManager) -> Tuple[List[Dict[str, Any]], int]:
    """Perform sliding compaction on the reserved memory area.

    Reorganizes allocated segments towards lower addresses (immediately following Nucleo_Base),
    eliminating holes and consolidating all free memory into a single contiguous block at the top.

    Returns:
        Tuple containing:
        - List of movement records: dicts with process_name, old_range, new_range, size.
        - Consolidated contiguous free block size in KB.
    """
    allocated_segments = [
        seg for seg in reserved_manager.segments
        if seg.is_allocated and seg.process_name != "Nucleo_Base"
    ]

    base_seg = reserved_manager.base_kernel_segment
    new_segments: List[MemorySegment] = [base_seg]
    moved_records: List[Dict[str, Any]] = []

    current_start = base_seg.end_address + 1  # 1024 KB

    for seg in allocated_segments:
        old_start = seg.start_address
        old_end = seg.end_address
        new_start = current_start
        new_end = current_start + seg.size - 1

        if old_start != new_start:
            moved_records.append({
                "process_name": seg.process_name,
                "old_range": (old_start, old_end),
                "new_range": (new_start, new_end),
                "size_kb": seg.size,
            })

        seg.start_address = new_start
        seg.end_address = new_end
        new_segments.append(seg)
        current_start = new_end + 1

    # Consolidate all remaining free space into a single contiguous segment
    total_capacity = reserved_manager.total_capacity_kb
    remaining_free_kb = total_capacity - current_start

    if remaining_free_kb > 0:
        consolidated_free_seg = MemorySegment(
            segment_id=reserved_manager._next_segment_id(),
            process_name=None,
            start_address=current_start,
            end_address=total_capacity - 1,
            size=remaining_free_kb,
            status=SegmentStatus.FREE,
        )
        new_segments.append(consolidated_free_seg)

    reserved_manager.segments = new_segments
    return moved_records, remaining_free_kb
