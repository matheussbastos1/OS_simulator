"""Simulation Kernel orchestrating services and maintaining global state."""

from typing import Any, Dict, Optional

from os_simulator.core.context import ExecutionContext
from os_simulator.core.ports import AuthorizationPort, BlockDevicePort, BootstrapSecurityPolicy
from os_simulator.core.types import AllocationStrategy
from os_simulator.filesystem.service import FileSystemService
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class SimulationKernel:
    """Central orchestration kernel for the OS Simulator."""

    def __init__(
        self,
        block_device: Optional[BlockDevicePort] = None,
        auth_port: Optional[AuthorizationPort] = None,
        default_strategy: AllocationStrategy = AllocationStrategy.INDEXED,
        disk_capacity: int = 16,
        block_size: int = 4096,
    ):
        self.context = ExecutionContext()
        self.auth = auth_port or BootstrapSecurityPolicy()
        self.device = block_device or InMemoryBlockDevice(capacity=disk_capacity, block_size=block_size)
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
