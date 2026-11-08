"""Simulation Kernel orchestrating services and maintaining global state."""

from typing import Any, Dict, Optional

from os_simulator.core.context import ExecutionContext
from os_simulator.core.ports import AuthorizationPort, BlockDevicePort, BootstrapSecurityPolicy
from os_simulator.core.types import AllocationStrategy
from os_simulator.filesystem.service import FileSystemService
from os_simulator.io.scheduler import DiskScheduler, SSTFScheduler
from os_simulator.io.service import IOManager
from os_simulator.io.ssd import SSDDevice
from os_simulator.storage.adapter import IOBlockDeviceAdapter
from os_simulator.storage.memory_block_device import InMemoryBlockDevice
from os_simulator.storage.physical_disk import PhysicalDisk
from os_simulator.storage.raid import RAID5Controller, RAIDController


class SimulationKernel:
    """Central orchestration kernel for the OS Simulator."""

    def __init__(
        self,
        block_device: Optional[BlockDevicePort] = None,
        auth_port: Optional[AuthorizationPort] = None,
        default_strategy: AllocationStrategy = AllocationStrategy.INDEXED,
        disk_capacity: int = 16,
        block_size: int = 4096,
        io_manager: Optional[IOManager] = None,
        raid_controller: Optional[RAIDController] = None,
        ssd_device: Optional[SSDDevice] = None,
        scheduler: Optional[DiskScheduler] = None,
    ):
        self.context = ExecutionContext()
        self.auth = auth_port or BootstrapSecurityPolicy()

        # 1. Initialize SSD simulation (available for SSD diagnostic and benchmark)
        self.ssd_device = ssd_device or SSDDevice(logical_capacity=16, block_size=block_size)

        # 2. Initialize RAID Controller
        if raid_controller is not None:
            self.raid_controller: Optional[RAIDController] = raid_controller
        elif block_device is None or isinstance(block_device, IOBlockDeviceAdapter):
            blocks_per_disk = max(8, (disk_capacity + 2) // 3 + 2)
            disks = [
                PhysicalDisk(disk_id=i, capacity_blocks=blocks_per_disk, block_size=block_size)
                for i in range(4)
            ]
            self.raid_controller = RAID5Controller(disks=disks, block_size=block_size)
        else:
            self.raid_controller = None

        # 3. Initialize IO Manager
        if io_manager is not None:
            self.io_manager = io_manager
        elif self.raid_controller is not None:
            active_scheduler = scheduler or SSTFScheduler(initial_head=53)
            self.io_manager = IOManager(storage_backend=self.raid_controller, scheduler=active_scheduler)
        else:
            self.io_manager = None

        # 4. Initialize Block Device
        if block_device is not None:
            self.device = block_device
            if isinstance(block_device, IOBlockDeviceAdapter):
                self.io_manager = block_device.io_manager
                if isinstance(block_device.io_manager.storage_backend, RAIDController):
                    self.raid_controller = block_device.io_manager.storage_backend
        else:
            if self.io_manager is not None and self.raid_controller is not None:
                self.device = IOBlockDeviceAdapter(
                    io_manager=self.io_manager,
                    logical_capacity=self.raid_controller.logical_capacity,
                    block_size=block_size,
                )
            else:
                self.device = InMemoryBlockDevice(capacity=disk_capacity, block_size=block_size)

        # 5. Initialize Filesystem Service
        self.fs_service = FileSystemService(
            block_device=self.device,
            auth_port=self.auth,
            default_strategy=default_strategy,
        )
        self.is_running = True

    def set_cwd(self, path: str) -> str:
        """Change current working directory in context."""
        canonical = self.fs_service.vfs.normalize_path(path, self.context.cwd)
        # Validate existence and directory type
        self.fs_service.vfs.get_directory(canonical)
        self.context.cwd = canonical
        return canonical

    def get_cwd(self) -> str:
        """Return canonical current working directory."""
        return self.context.cwd

    def get_prompt(self) -> str:
        """Format shell prompt string according to user and cwd."""
        symbol = "#" if self.context.is_root() else "$"
        return f"[{self.context.username}@ubuntu-simulator:{self.context.cwd}]{symbol} "
