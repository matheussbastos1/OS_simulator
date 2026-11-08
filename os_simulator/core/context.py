"""Execution context for active sessions in OS Simulator."""

from dataclasses import dataclass, field
from typing import List

from os_simulator.core.types import PrivilegeMode


@dataclass
class ExecutionContext:
    """Maintains active user identity, working directory, and privilege level."""
    user_id: int = 0
    username: str = "root"
    groups: List[str] = field(default_factory=lambda: ["root", "admin"])
    privilege_mode: PrivilegeMode = PrivilegeMode.KERNEL_MODE
    cwd: str = "/"

    def is_root(self) -> bool:
        """Return True if active user has administrative privileges."""
        return self.user_id == 0 or self.username == "root" or self.privilege_mode == PrivilegeMode.KERNEL_MODE
