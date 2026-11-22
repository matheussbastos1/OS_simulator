"""Memory management subsystem initialization."""

from os_simulator.memory.segment import MemorySegment, ReservedMemoryManager
from os_simulator.memory.compaction import compact_reserved_memory
from os_simulator.memory.paging import PageTableEntry, PageTable, Frame, PhysicalMemory
from os_simulator.memory.mmu import MMU
from os_simulator.memory.replacement import (
    PageReplacementPolicy,
    LRUReplacement,
    SecondChanceReplacement,
    create_replacement_policy,
)
from os_simulator.memory.swap import SwapSlot, SwapManager
from os_simulator.memory.service import MemoryManager

__all__ = [
    "MemorySegment",
    "ReservedMemoryManager",
    "compact_reserved_memory",
    "PageTableEntry",
    "PageTable",
    "Frame",
    "PhysicalMemory",
    "MMU",
    "PageReplacementPolicy",
    "LRUReplacement",
    "SecondChanceReplacement",
    "create_replacement_policy",
    "SwapSlot",
    "SwapManager",
    "MemoryManager",
]
