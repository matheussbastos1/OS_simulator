"""Page replacement policies: LRU (Least Recently Used) and Second Chance (Clock)."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from os_simulator.core.types import ReplacementAlgorithm
from os_simulator.memory.paging import PageTableEntry


class PageReplacementPolicy(ABC):
    """Abstract base class for page replacement strategies."""

    @abstractmethod
    def select_victim(
        self, candidates: List[Tuple[int, PageTableEntry]]
    ) -> Tuple[int, PageTableEntry]:
        """Select a victim frame and entry from list of (frame_id, entry) candidates."""
        pass

    @abstractmethod
    def record_access(
        self, frame_id: int, entry: PageTableEntry, timestamp: float
    ) -> None:
        """Update policy state when a frame/page is accessed."""
        pass

    def on_frame_allocated(self, frame_id: int, entry: PageTableEntry) -> None:
        """Hook called when a page is allocated into a frame."""
        pass

    def on_frame_freed(self, frame_id: int) -> None:
        """Hook called when a frame is freed."""
        pass


class LRUReplacement(PageReplacementPolicy):
    """Least Recently Used (LRU) page replacement policy.

    Selects the page with the lowest last_access timestamp.
    Ties are broken deterministically by lowest frame_id.
    """

    def select_victim(
        self, candidates: List[Tuple[int, PageTableEntry]]
    ) -> Tuple[int, PageTableEntry]:
        if not candidates:
            raise ValueError("Lista de candidatos para substituição LRU está vazia.")

        # Minimum by (last_access, frame_id)
        victim = min(candidates, key=lambda item: (item[1].last_access, item[0]))
        return victim

    def record_access(
        self, frame_id: int, entry: PageTableEntry, timestamp: float
    ) -> None:
        entry.last_access = timestamp
        entry.referenced = True


class SecondChanceReplacement(PageReplacementPolicy):
    """Second Chance (Clock) page replacement algorithm.

    Maintains a circular clock pointer across candidate frames.
    Inspects referenced bit:
      - If referenced == True: sets referenced = False, gives second chance, advances pointer.
      - If referenced == False: selects as victim, advances pointer, returns victim.
    """

    def __init__(self):
        self.clock_pointer: int = 0

    def select_victim(
        self, candidates: List[Tuple[int, PageTableEntry]]
    ) -> Tuple[int, PageTableEntry]:
        if not candidates:
            raise ValueError("Lista de candidatos para substituição Segunda Chance está vazia.")

        n = len(candidates)
        # Ensure clock pointer is within bounds
        self.clock_pointer = self.clock_pointer % n

        # Up to 2 full revolutions (2 * n iterations)
        for _ in range(2 * n):
            frame_id, entry = candidates[self.clock_pointer]
            if not entry.referenced:
                # Found victim
                victim = (frame_id, entry)
                self.clock_pointer = (self.clock_pointer + 1) % n
                return victim
            else:
                # Second chance: clear reference bit and advance
                entry.referenced = False
                self.clock_pointer = (self.clock_pointer + 1) % n

        # Fallback (should not occur since bits are cleared on first pass)
        victim = candidates[self.clock_pointer]
        self.clock_pointer = (self.clock_pointer + 1) % n
        return victim

    def record_access(
        self, frame_id: int, entry: PageTableEntry, timestamp: float
    ) -> None:
        entry.referenced = True
        entry.last_access = timestamp

    def on_frame_freed(self, frame_id: int) -> None:
        # Keep clock pointer within reasonable bounds
        self.clock_pointer = 0


def create_replacement_policy(algorithm: ReplacementAlgorithm) -> PageReplacementPolicy:
    """Factory function for page replacement policies."""
    if algorithm == ReplacementAlgorithm.LRU:
        return LRUReplacement()
    elif algorithm == ReplacementAlgorithm.SECOND_CHANCE:
        return SecondChanceReplacement()
    raise ValueError(f"Algoritmo de substituição não suportado: {algorithm}")
