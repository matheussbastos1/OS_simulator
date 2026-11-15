"""Provisional authorization policy for Stages 1 and 2 of OS Simulator."""

from typing import Any, Optional

from os_simulator.core.context import ExecutionContext
from os_simulator.core.ports import AuthorizationPort, BootstrapSecurityPolicy

__all__ = ["BootstrapSecurityPolicy"]
