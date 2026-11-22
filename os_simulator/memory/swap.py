"""Simulated swap storage partition operating over BlockDevicePort."""

from typing import Any, Dict, List, Optional, Tuple

from os_simulator.core.exceptions import SwapException, SwapFullException
from os_simulator.core.ports import BlockDevicePort
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class SwapSlot:
    """Represents a swap partition slot tracking stored page metadata."""

    def __init__(self, slot_id: int, pid: Optional[int] = None, logical_page: Optional[int] = None):
        self.slot_id = slot_id
        self.pid = pid
        self.logical_page = logical_page
        self.occupied: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "occupied": self.occupied,
            "pid": self.pid,
            "logical_page": self.logical_page,
        }


class SwapManager:
    """Manages simulated swap partition over BlockDevicePort."""

    def __init__(
        self,
        total_slots: int = 64,
        slot_size: int = 4096,
        block_device: Optional[BlockDevicePort] = None,
        base_block: int = 0,
    ):
        self.total_slots = total_slots
        self.slot_size = slot_size
        self.base_block = base_block
        # Dedicated or shared block device implementing BlockDevicePort
        self.block_device = block_device or InMemoryBlockDevice(capacity=total_slots, block_size=slot_size)
        self.slots_in_use: Dict[int, Tuple[int, int]] = {}  # slot_id -> (pid, logical_page)

    def allocate_slot(self, pid: int, logical_page: int) -> int:
        """Find and allocate the first free swap slot."""
        for slot_id in range(self.total_slots):
            if slot_id not in self.slots_in_use:
                self.slots_in_use[slot_id] = (pid, logical_page)
                return slot_id

        raise SwapFullException(
            f"Partição de Swap esgotada: todos os {self.total_slots} slots estão ocupados."
        )

    def write_page(self, slot_id: int, data: bytes) -> None:
        """Write page data to swap slot via block device."""
        if slot_id not in self.slots_in_use:
            raise SwapException(f"Slot de swap {slot_id} não está alocado.")

        padded_data = data[:self.slot_size].ljust(self.slot_size, b"\x00")
        target_block = self.base_block + slot_id
        self.block_device.write_block(target_block, padded_data)

    def read_page(self, slot_id: int) -> bytes:
        """Read page data from swap slot via block device."""
        if slot_id not in self.slots_in_use:
            raise SwapException(f"Slot de swap {slot_id} não está alocado.")

        target_block = self.base_block + slot_id
        return self.block_device.read_block(target_block)

    def free_slot(self, slot_id: int) -> None:
        """Free allocated swap slot and clear its block."""
        if slot_id in self.slots_in_use:
            del self.slots_in_use[slot_id]
            try:
                self.block_device.write_block(self.base_block + slot_id, b"\x00" * self.slot_size)
            except Exception:
                pass

    def free_process_slots(self, pid: int) -> List[int]:
        """Free all swap slots belonging to a process."""
        slots_to_free = [sid for sid, (p, _) in self.slots_in_use.items() if p == pid]
        for sid in slots_to_free:
            self.free_slot(sid)
        return slots_to_free

    def get_used_slots_count(self) -> int:
        """Count slots currently holding evicted pages."""
        return len(self.slots_in_use)

    def get_free_slots_count(self) -> int:
        """Count available swap slots."""
        return self.total_slots - len(self.slots_in_use)

    def get_slots_for_process(self, pid: int) -> List[Tuple[int, int]]:
        """Return list of (slot_id, logical_page) for a process."""
        return [(sid, page) for sid, (p, page) in self.slots_in_use.items() if p == pid]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_slots": self.total_slots,
            "slot_size": self.slot_size,
            "used_slots": self.get_used_slots_count(),
            "free_slots": self.get_free_slots_count(),
            "slots_in_use": {
                str(sid): {"pid": pid, "logical_page": page}
                for sid, (pid, page) in self.slots_in_use.items()
            },
        }
