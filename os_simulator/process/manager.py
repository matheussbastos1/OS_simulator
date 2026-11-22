"""Process manager orchestrating process lifecycles and tracking PCBs."""

from typing import Dict, List, Optional, Union

from os_simulator.core.exceptions import (
    InvalidProcessStateException,
    PermissionDeniedException,
    ProcessAlreadyExistsException,
    ProcessNotFoundException,
)
from os_simulator.core.types import ProcessState, ProcessType
from os_simulator.process.pcb import Process


class ProcessManager:
    """Manages process creation, lookup, termination, and process table."""

    def __init__(self, start_pid: int = 100):
        self.processes: Dict[int, Process] = {}
        self.name_to_pid: Dict[str, int] = {}
        self._next_pid: int = start_pid

        # Initialize Base Kernel (PID 0)
        self.kernel_process = Process(
            pid=0,
            name="Nucleo_Base",
            size_bytes=1024 * 1024,
            process_type=ProcessType.CRITICAL,
            owner="root",
            state=ProcessState.RUNNING,
        )
        self.processes[0] = self.kernel_process
        self.name_to_pid["Nucleo_Base"] = 0

    def create_process(
        self,
        name: str,
        size_bytes: int,
        process_type: ProcessType = ProcessType.NORMAL,
        owner: str = "root",
    ) -> Process:
        """Create and register a new process."""
        if not name or not name.strip():
            raise ValueError("Nome do processo não pode ser vazio.")

        name = name.strip()
        if name in self.name_to_pid:
            existing_pid = self.name_to_pid[name]
            existing_proc = self.processes[existing_pid]
            if existing_proc.state != ProcessState.TERMINATED:
                raise ProcessAlreadyExistsException(
                    f"Processo '{name}' já existe e está ativo (PID {existing_pid})."
                )

        if size_bytes <= 0:
            raise ValueError(f"Tamanho do processo deve ser maior que zero (recebido: {size_bytes} bytes).")

        pid = self._next_pid
        self._next_pid += 1

        proc = Process(
            pid=pid,
            name=name,
            size_bytes=size_bytes,
            process_type=process_type,
            owner=owner,
            state=ProcessState.READY,
        )
        self.processes[pid] = proc
        self.name_to_pid[name] = pid
        return proc

    def get_process(self, identifier: Union[str, int]) -> Process:
        """Find process by PID or name."""
        if isinstance(identifier, int):
            if identifier in self.processes:
                return self.processes[identifier]
            raise ProcessNotFoundException(f"Processo com PID {identifier} não encontrado.")

        id_str = str(identifier).strip()
        if id_str.isdigit() and int(id_str) in self.processes:
            return self.processes[int(id_str)]

        if id_str in self.name_to_pid:
            pid = self.name_to_pid[id_str]
            return self.processes[pid]

        for proc in self.processes.values():
            if proc.name.lower() == id_str.lower():
                return proc

        raise ProcessNotFoundException(f"Processo '{identifier}' não encontrado.")

    def terminate_process(self, identifier: Union[str, int]) -> Process:
        """Terminate a process by name or PID."""
        proc = self.get_process(identifier)

        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException("O núcleo base do sistema operacional não pode ser encerrado.")

        if proc.state == ProcessState.TERMINATED:
            raise InvalidProcessStateException(f"Processo '{proc.name}' (PID {proc.pid}) já está encerrado.")

        proc.terminate()
        return proc

    def list_processes(self, active_only: bool = False) -> List[Process]:
        """List all tracked processes."""
        if active_only:
            return [p for p in self.processes.values() if p.state != ProcessState.TERMINATED]
        return list(self.processes.values())
