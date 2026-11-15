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

    @property
    def primary_group(self) -> str:
        """Return primary group of the active user."""
        return self.groups[0] if self.groups else "users"

    def is_kernel_mode(self) -> bool:
        """Return True if current privilege mode is KERNEL_MODE."""
        return self.privilege_mode == PrivilegeMode.KERNEL_MODE

    def is_user_mode(self) -> bool:
        """Return True if current privilege mode is USER_MODE."""
        return self.privilege_mode == PrivilegeMode.USER_MODE

    def is_admin(self) -> bool:
        """Check administrative privileges (equivalent to is_root)."""
        return self.is_root()

    def has_group(self, group: str) -> bool:
        """Check if user belongs to the specified group."""
        return group in self.groups

