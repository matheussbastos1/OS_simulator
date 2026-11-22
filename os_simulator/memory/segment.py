"""Contiguous memory segment and reserved memory manager for OS Simulator."""

from typing import Any, Dict, List, Optional

from os_simulator.core.exceptions import (
    MemoryFragmentationException,
    OutOfMemoryException,
    PermissionDeniedException,
)
from os_simulator.core.types import SegmentStatus


class MemorySegment:
    """Represents a contiguous slice of reserved physical memory in KB."""

    def __init__(
        self,
        segment_id: int,
        process_name: Optional[str],
        start_address: int,
        end_address: int,
        size: int,
        status: SegmentStatus = SegmentStatus.FREE,
    ):
        self.segment_id = segment_id
        self.process_name = process_name
        self.start_address = start_address  # in KB
        self.end_address = end_address      # in KB (inclusive: start + size - 1)
        self.size = size                    # in KB
        self.status = status

    @property
    def is_free(self) -> bool:
        """Return True if segment is free."""
        return self.status == SegmentStatus.FREE

    @property
    def is_allocated(self) -> bool:
        """Return True if segment is occupied."""
        return self.status == SegmentStatus.ALLOCATED

    def to_dict(self) -> Dict[str, Any]:
        """Serialize segment to dictionary."""
        return {
            "segment_id": self.segment_id,
            "process_name": self.process_name,
            "start_address": self.start_address,
            "end_address": self.end_address,
            "size_kb": self.size,
            "status": self.status.value,
        }

    def __repr__(self) -> str:
        name = self.process_name or "[BURACO LIVRE]"
        return f"[{self.start_address:04d} - {self.end_address:04d} KB] : {name} ({self.size} KB) - {self.status.value}"


class ReservedMemoryManager:
    """Manages the contiguous Reserved Memory Region (Kernel & Critical Drivers)."""

    def __init__(self, total_capacity_kb: int = 4096, base_kernel_size_kb: int = 1024):
        self.total_capacity_kb = total_capacity_kb
        self.base_kernel_size_kb = base_kernel_size_kb
        self._segment_counter = 0

        # Segment 0: Base Kernel (immutable, permanently occupying 0 - 1023 KB)
        self.base_kernel_segment = MemorySegment(
            segment_id=self._next_segment_id(),
            process_name="Nucleo_Base",
            start_address=0,
            end_address=base_kernel_size_kb - 1,
            size=base_kernel_size_kb,
            status=SegmentStatus.ALLOCATED,
        )

        # Initial free segment for the rest of reserved memory
        initial_free_size = total_capacity_kb - base_kernel_size_kb
        initial_free_segment = MemorySegment(
            segment_id=self._next_segment_id(),
            process_name=None,
            start_address=base_kernel_size_kb,
            end_address=total_capacity_kb - 1,
            size=initial_free_size,
            status=SegmentStatus.FREE,
        )

        self.segments: List[MemorySegment] = [self.base_kernel_segment, initial_free_segment]

    def _next_segment_id(self) -> int:
        sid = self._segment_counter
        self._segment_counter += 1
        return sid

    def get_total_free_kb(self) -> int:
        """Total free memory across all free segments in KB."""
        return sum(seg.size for seg in self.segments if seg.is_free)

    def get_total_allocated_kb(self) -> int:
        """Total allocated memory in KB."""
        return sum(seg.size for seg in self.segments if seg.is_allocated)

    def get_max_contiguous_free_kb(self) -> int:
        """Size in KB of the largest contiguous free segment."""
        free_sizes = [seg.size for seg in self.segments if seg.is_free]
        return max(free_sizes) if free_sizes else 0

    def get_external_fragmentation_kb(self) -> int:
        """External fragmentation = Total Free KB - Largest Contiguous Free KB."""
        total_free = self.get_total_free_kb()
        max_contiguous = self.get_max_contiguous_free_kb()
        return total_free - max_contiguous

    def allocate(self, process_name: str, size_kb: int) -> MemorySegment:
        """Allocate a contiguous slice of reserved memory using First-Fit."""
        if not process_name:
            raise ValueError("Nome do processo não pode ser vazio.")
        if size_kb <= 0:
            raise ValueError(f"Tamanho de alocação deve ser positivo ({size_kb} KB recebido).")

        # Check if process already allocated
        for seg in self.segments:
            if seg.is_allocated and seg.process_name == process_name:
                raise ValueError(f"Processo '{process_name}' já possui alocação na área reservada.")

        # First-Fit search
        for idx, seg in enumerate(self.segments):
            if seg.is_free and seg.size >= size_kb:
                if seg.size == size_kb:
                    seg.status = SegmentStatus.ALLOCATED
                    seg.process_name = process_name
                    return seg
                else:
                    # Split segment
                    allocated_seg = MemorySegment(
                        segment_id=self._next_segment_id(),
                        process_name=process_name,
                        start_address=seg.start_address,
                        end_address=seg.start_address + size_kb - 1,
                        size=size_kb,
                        status=SegmentStatus.ALLOCATED,
                    )
                    remaining_free = MemorySegment(
                        segment_id=self._next_segment_id(),
                        process_name=None,
                        start_address=seg.start_address + size_kb,
                        end_address=seg.end_address,
                        size=seg.size - size_kb,
                        status=SegmentStatus.FREE,
                    )
                    self.segments[idx:idx + 1] = [allocated_seg, remaining_free]
                    return allocated_seg

        # If not found, diagnose cause (OOM vs External Fragmentation)
        total_free = self.get_total_free_kb()
        max_contiguous = self.get_max_contiguous_free_kb()

        if total_free >= size_kb:
            raise MemoryFragmentationException(
                f"Falha de alocação por fragmentação externa: espaço livre total ({total_free} KB) "
                f"é suficiente para {size_kb} KB, mas o maior bloco contíguo disponível é de {max_contiguous} KB."
            )
        else:
            raise OutOfMemoryException(
                f"Memória reservada esgotada: solicitado {size_kb} KB, disponível total {total_free} KB."
            )

    def free(self, process_name: str) -> None:
        """Free memory allocated to process and coalesce adjacent free holes."""
        if process_name == "Nucleo_Base":
            raise PermissionDeniedException("O núcleo base do sistema operacional não pode ser liberado.")

        found_idx = None
        for idx, seg in enumerate(self.segments):
            if seg.is_allocated and seg.process_name == process_name:
                found_idx = idx
                break

        if found_idx is None:
            raise ValueError(f"Processo '{process_name}' não possui alocação ativa na área reservada.")

        target = self.segments[found_idx]
        target.status = SegmentStatus.FREE
        target.process_name = None

        self._coalesce()

    def _coalesce(self) -> None:
        """Merge adjacent free memory segments into single contiguous blocks."""
        coalesced: List[MemorySegment] = []
        for seg in self.segments:
            if not coalesced:
                coalesced.append(seg)
                continue

            last = coalesced[-1]
            if last.is_free and seg.is_free:
                # Merge seg into last
                last.end_address = seg.end_address
                last.size = last.size + seg.size
            else:
                coalesced.append(seg)
        self.segments = coalesced

    def get_segment_for_process(self, process_name: str) -> Optional[MemorySegment]:
        """Find segment by process name."""
        for seg in self.segments:
            if seg.is_allocated and seg.process_name == process_name:
                return seg
        return None

    def get_segments(self) -> List[MemorySegment]:
        """Return shallow copy of segment list."""
        return list(self.segments)
