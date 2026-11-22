"""Virtual memory paging structures: PageTable, PageTableEntry, Frame, and PhysicalMemory."""

import math
from typing import Any, Dict, List, Optional

from os_simulator.core.exceptions import InvalidAddressException
from os_simulator.core.types import PageOrigin


class PageTableEntry:
    """Represents a single entry in a process's page table."""

    def __init__(
        self,
        logical_page: int,
        bytes_used: int = 4096,
        page_origin: PageOrigin = PageOrigin.ZERO_FILL_ON_DEMAND,
        frame_id: Optional[int] = None,
        present: bool = False,
        dirty: bool = False,
        referenced: bool = False,
        last_access: float = 0.0,
        swap_slot_id: Optional[int] = None,
    ):
        self.logical_page = logical_page
        self.bytes_used = bytes_used
        self.page_origin = page_origin
        self.frame_id = frame_id
        self.present = present
        self.dirty = dirty
        self.referenced = referenced
        self.last_access = last_access
        self.swap_slot_id = swap_slot_id

    def to_dict(self) -> Dict[str, Any]:
        """Serialize page table entry to dict."""
        return {
            "logical_page": self.logical_page,
            "bytes_used": self.bytes_used,
            "page_origin": self.page_origin.value,
            "frame_id": self.frame_id,
            "present": self.present,
            "dirty": self.dirty,
            "referenced": self.referenced,
            "last_access": self.last_access,
            "swap_slot_id": self.swap_slot_id,
        }

    def __repr__(self) -> str:
        state = f"Frame={self.frame_id}" if self.present else f"Ausente({self.page_origin.value})"
        bits = f"[P={int(self.present)} D={int(self.dirty)} R={int(self.referenced)}]"
        return f"<PTE page={self.logical_page} {state} {bits} t={self.last_access:.1f}>"


class PageTable:
    """Per-process virtual memory page table."""

    def __init__(self, pid: int, process_size_bytes: int, page_size: int = 4096):
        self.pid = pid
        self.process_size_bytes = process_size_bytes
        self.page_size = page_size
        self.entries: Dict[int, PageTableEntry] = {}

        # Calculate number of pages
        if process_size_bytes <= 0:
            self.total_pages = 0
        else:
            self.total_pages = math.ceil(process_size_bytes / page_size)

        # Initialize page entries
        remaining = process_size_bytes
        for page_idx in range(self.total_pages):
            used = min(remaining, page_size)
            remaining -= used
            # By default, page 0 may be code/binary image, others zero-fill on demand
            origin = PageOrigin.PROCESS_IMAGE if page_idx == 0 else PageOrigin.ZERO_FILL_ON_DEMAND
            self.entries[page_idx] = PageTableEntry(
                logical_page=page_idx,
                bytes_used=used,
                page_origin=origin,
                present=False,
                frame_id=None,
            )

    @property
    def internal_fragmentation(self) -> int:
        """Internal fragmentation in bytes (waste in the final allocated page)."""
        if self.total_pages == 0:
            return 0
        last_page = self.entries[self.total_pages - 1]
        return self.page_size - last_page.bytes_used

    def get_entry(self, logical_page: int) -> PageTableEntry:
        """Get entry for a logical page or raise InvalidAddressException."""
        if logical_page not in self.entries:
            raise InvalidAddressException(
                f"Página lógica {logical_page} inválida para processo PID {self.pid} "
                f"(total de páginas alocadas: {self.total_pages})."
            )
        return self.entries[logical_page]

    def get_present_entries(self) -> List[PageTableEntry]:
        """Return all entries currently mapped to physical frames."""
        return [entry for entry in self.entries.values() if entry.present]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize page table to dictionary."""
        return {
            "pid": self.pid,
            "total_pages": self.total_pages,
            "page_size": self.page_size,
            "process_size_bytes": self.process_size_bytes,
            "internal_fragmentation": self.internal_fragmentation,
            "entries": [entry.to_dict() for entry in self.entries.values()],
        }


class Frame:
    """Represents a physical memory frame (moldura) in dynamic RAM."""

    def __init__(self, frame_id: int, size: int = 4096):
        self.frame_id = frame_id
        self.size = size
        self.data = bytearray(size)
        self.occupied: bool = False
        self.owner_pid: Optional[int] = None
        self.logical_page: Optional[int] = None

    def allocate(self, pid: int, logical_page: int, data: Optional[bytes] = None) -> None:
        """Allocate frame to process page."""
        self.occupied = True
        self.owner_pid = pid
        self.logical_page = logical_page
        if data is not None:
            self.write_data(data)
        else:
            self.fill_zeros()

    def free(self) -> None:
        """Free frame and clear its data."""
        self.occupied = False
        self.owner_pid = None
        self.logical_page = None
        self.fill_zeros()

    def fill_zeros(self) -> None:
        """Zero out frame memory."""
        self.data[:] = b"\x00" * self.size

    def write_data(self, data: bytes, offset: int = 0) -> None:
        """Write bytes to frame memory."""
        end = min(offset + len(data), self.size)
        self.data[offset:end] = data[:end - offset]

    def read_data(self, offset: int = 0, length: Optional[int] = None) -> bytes:
        """Read bytes from frame memory."""
        end = self.size if length is None else min(offset + length, self.size)
        return bytes(self.data[offset:end])

    def to_dict(self) -> Dict[str, Any]:
        """Serialize frame state to dict."""
        return {
            "frame_id": self.frame_id,
            "occupied": self.occupied,
            "owner_pid": self.owner_pid,
            "logical_page": self.logical_page,
            "size": self.size,
        }

    def __repr__(self) -> str:
        if not self.occupied:
            return f"<Frame {self.frame_id}: LIVRE>"
        return f"<Frame {self.frame_id}: PID={self.owner_pid} Page={self.logical_page}>"


class PhysicalMemory:
    """Simulated Dynamic Physical RAM holding frames for user processes."""

    def __init__(self, num_frames: int = 16, frame_size: int = 4096):
        self.num_frames = num_frames
        self.frame_size = frame_size
        self.frames: List[Frame] = [Frame(frame_id=i, size=frame_size) for i in range(num_frames)]

    @property
    def total_capacity_bytes(self) -> int:
        """Total dynamic RAM capacity in bytes."""
        return self.num_frames * self.frame_size

    def get_free_frame_id(self) -> Optional[int]:
        """Return the lowest-index free frame ID, or None if RAM is full."""
        for frame in self.frames:
            if not frame.occupied:
                return frame.frame_id
        return None

    def get_frame(self, frame_id: int) -> Frame:
        """Get frame by ID."""
        if frame_id < 0 or frame_id >= self.num_frames:
            raise IndexError(f"Frame ID {frame_id} fora dos limites (0 a {self.num_frames - 1}).")
        return self.frames[frame_id]

    def allocate_frame(self, frame_id: int, pid: int, logical_page: int, data: Optional[bytes] = None) -> Frame:
        """Allocate specific frame."""
        frame = self.get_frame(frame_id)
        frame.allocate(pid=pid, logical_page=logical_page, data=data)
        return frame

    def free_frame(self, frame_id: int) -> None:
        """Free specific frame."""
        frame = self.get_frame(frame_id)
        frame.free()

    def free_frames_for_process(self, pid: int) -> List[int]:
        """Free all frames allocated to a process."""
        freed = []
        for frame in self.frames:
            if frame.occupied and frame.owner_pid == pid:
                frame.free()
                freed.append(frame.frame_id)
        return freed

    def get_occupied_count(self) -> int:
        """Count occupied frames."""
        return sum(1 for f in self.frames if f.occupied)

    def get_free_count(self) -> int:
        """Count free frames."""
        return sum(1 for f in self.frames if not f.occupied)
