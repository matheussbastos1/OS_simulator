"""Stage 5 CLI command handlers for processes, threads, scheduling, syscalls, concurrency, and metrics."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from os_simulator.core.exceptions import (
    DeadlockDetectedException,
    OSSimulatorException,
    SimulationStallException,
)
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import IOProfileType, ProcessState, SimulationEventType, SyscallType
from os_simulator.process.pcb import Process
from os_simulator.process.syscalls import IOProfile
from os_simulator.process.thread import SimulatedThread


class CommandResult:
    """Encapsulates the execution result of a CLI command."""

    def __init__(
        self,
        success: bool,
        output: str = "",
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.output = output
        self.error = error
        self.data = data or {}

    def __str__(self) -> str:
        return self.output if self.success else f"Erro: {self.error}"


def parse_int_arg(raw: str, field_name: str, min_val: Optional[int] = None) -> int:
    """Parse an integer CLI argument strictly and enforce optional lower bound."""
    clean = str(raw).strip()
    if not clean:
        raise ValueError(f"{field_name} inválido: valor vazio.")
    try:
        value = int(clean, 10)
    except ValueError as exc:
        raise ValueError(f"{field_name} inválido: '{raw}' deve ser um número inteiro.") from exc
    if min_val is not None and value < min_val:
        raise ValueError(f"{field_name} inválido: deve ser um inteiro >= {min_val} (recebido: {value}).")
    return value


def parse_pages_pattern(raw: str) -> List[Tuple[int, bool]]:
    """Parse comma-separated logical page access list (e.g. '0,1,0,2' or '0,1:w')."""
    clean = str(raw).strip()
    if not clean:
        raise ValueError(
            "Padrão de páginas (--pages) não pode ser vazio. Exemplo: --pages 0,1,0,2"
        )
    pattern: List[Tuple[int, bool]] = []
    for item in clean.split(","):
        token = item.strip()
        if not token:
            raise ValueError(
                f"Padrão de páginas (--pages) malformado: '{raw}'. Exemplo válido: 0,1,0,2"
            )
        is_write = False
        page_part = token
        if ":" in token:
            page_part, mode = token.split(":", 1)
            mode_norm = mode.strip().lower()
            if mode_norm in ("w", "write", "rw"):
                is_write = True
            elif mode_norm in ("r", "read"):
                is_write = False
            else:
                raise ValueError(
                    f"Modo de acesso inválido em '--pages': '{token}'. Use 'r' ou 'w' (ex.: 1:w)."
                )
        elif token[-1].lower() in ("w", "r") and token[:-1].isdigit():
            is_write = token[-1].lower() == "w"
            page_part = token[:-1]

        page_num = parse_int_arg(page_part, "Página lógica (--pages)", min_val=0)
        pattern.append((page_num, is_write))
    return pattern


def build_io_profile(
    io_profile_str: Optional[str],
    io_every: Optional[int],
    io_duration: Optional[int],
    seed_val: Optional[int],
    default_seed: int,
) -> Any:
    """Construct a validated IOProfile or IOProfileType from optional CLI parameters."""
    if (
        io_profile_str is None
        and io_every is None
        and io_duration is None
        and seed_val is None
    ):
        return IOProfileType.NONE

    eff_seed = seed_val if seed_val is not None else default_seed
    if io_profile_str is not None:
        ptype = IOProfileType.from_string(io_profile_str)
    elif io_every is not None:
        ptype = IOProfileType.PERIODIC
    else:
        ptype = IOProfileType.NONE

    if ptype == IOProfileType.PERIODIC:
        return IOProfile(
            profile_type=IOProfileType.PERIODIC,
            interval_cpu_ms=io_every if io_every is not None else 4,
            default_duration_ms=io_duration if io_duration is not None else 4,
            seed=eff_seed,
        )

    if ptype == IOProfileType.RANDOM:
        if io_duration is not None:
            return IOProfile(
                profile_type=IOProfileType.RANDOM,
                interval_cpu_ms=io_every,
                default_duration_ms=io_duration,
                min_duration_ms=io_duration,
                max_duration_ms=io_duration,
                seed=eff_seed,
            )
        return IOProfile(
            profile_type=IOProfileType.RANDOM,
            interval_cpu_ms=io_every,
            seed=eff_seed,
        )

    return IOProfile(
        profile_type=ptype,
        interval_cpu_ms=io_every,
        default_duration_ms=io_duration if io_duration is not None else 4,
        seed=eff_seed,
    )


def describe_io_profile(io_profile: Any) -> str:
    """Format an IOProfile or IOProfileType into a concise Portuguese label."""
    if isinstance(io_profile, IOProfile):
        ptype = io_profile.profile_type.value
        if io_profile.profile_type == IOProfileType.PERIODIC:
            return (
                f"{ptype} (a cada {io_profile.interval_cpu_ms} ms CPU, "
                f"duração={io_profile.default_duration_ms} ms)"
            )
        if io_profile.profile_type == IOProfileType.RANDOM:
            return (
                f"{ptype} (seed={io_profile.seed}, prob={io_profile.io_probability:.2f}, "
                f"duração={io_profile.min_duration_ms}..{io_profile.max_duration_ms} ms)"
            )
        return ptype
    if isinstance(io_profile, IOProfileType):
        return io_profile.value
    return str(io_profile)


def parse_cli_args(
    args: List[str],
    value_flags: Optional[Set[str]] = None,
    bool_flags: Optional[Set[str]] = None,
    aliases: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Set[str], List[str]]:
    """Parse ``--key value``, ``--key=value``, boolean flags, and positional tokens uniformly."""
    vflags = value_flags or set()
    bflags = bool_flags or set()
    alias_map = aliases or {}

    values: Dict[str, str] = {}
    flags_set: Set[str] = set()
    positionals: List[str] = []

    idx = 0
    while idx < len(args):
        raw_tok = args[idx]
        if raw_tok.startswith("-") and raw_tok != "-":
            if "=" in raw_tok:
                raw_key, raw_val = raw_tok.split("=", 1)
                canon = alias_map.get(raw_key, raw_key)
                if canon not in vflags:
                    raise ValueError(f"Parâmetro desconhecido ou não aceita valor inline: '{raw_key}'.")
                values[canon] = raw_val
                idx += 1
                continue

            canon = alias_map.get(raw_tok, raw_tok)
            if canon in bflags:
                flags_set.add(canon)
                idx += 1
                continue
            if canon in vflags:
                if idx + 1 >= len(args):
                    raise ValueError(f"Valor ausente para o parâmetro '{raw_tok}'.")
                values[canon] = args[idx + 1]
                idx += 2
                continue
            raise ValueError(f"Parâmetro desconhecido: '{raw_tok}'.")

        positionals.append(raw_tok)
        idx += 1

    return values, flags_set, positionals


class Stage5ProcessCommands:
    """CLI handlers for Stage 5 process lifecycle, scheduling, syscalls, sync, and metrics."""

    def __init__(self, kernel: SimulationKernel) -> None:
        self.kernel = kernel

    def _handle_exception(self, exc: Exception) -> CommandResult:
        if isinstance(exc, DeadlockDetectedException):
            return CommandResult(
                success=False,
                error=f"[DEADLOCK DETECTADO] {exc}",
                data={
                    "deadlock": True,
                    "stall": False,
                    "cycle": list(exc.cycle),
                    "clock_ms": self.kernel.clock.now_ms,
                },
            )
        if isinstance(exc, SimulationStallException):
            return CommandResult(
                success=False,
                error=f"[ESTAGNAÇÃO DETECTADA] {exc}",
                data={
                    "deadlock": False,
                    "stall": True,
                    "clock_ms": self.kernel.clock.now_ms,
                },
            )
        if isinstance(exc, (OSSimulatorException, ValueError)):
            return CommandResult(success=False, error=str(exc))
        raise exc

    def _get_blocked_threads(self) -> List[SimulatedThread]:
        return [
            t
            for t in self.kernel.process_manager.list_threads()
            if ProcessState.normalize(t.state) == ProcessState.BLOCKED
        ]

    @staticmethod
    def _format_process_block_reason(proc: Process) -> str:
        blocked_threads = [
            t
            for t in proc.threads.values()
            if ProcessState.normalize(t.state) == ProcessState.BLOCKED
        ]
        if not blocked_threads:
            return "-"
        parts = []
        for t in blocked_threads:
            target = f"({t.blocked_on})" if t.blocked_on else ""
            parts.append(f"{t.name}:{t.block_reason.value}{target}")
        return ", ".join(parts)

    @staticmethod
    def _validate_supported_event_names() -> str:
        return ", ".join(ev.value for ev in SimulationEventType)

    def _format_run_stop_reason(self, reason: str) -> str:
        mapping = {
            "COMPLETED": "Simulação concluída (sem pendências)",
            "MAX_MS_REACHED": "Limite --max-ms atingido",
            "TARGET_PROCESS_TERMINATED": "Processo alvo encerrado",
            "TARGET_EVENT_REACHED": "Evento alvo atingido",
            "STEP_COMPLETE": "Passo concluído",
            "IDLE_EMPTY": "Fila de prontos e eventos vazias",
        }
        return mapping.get(reason, reason)

    def cmd_ps(self, args: List[str]) -> CommandResult:
        """List simulated processes, threads, states, priorities, CPU counters, and block reasons."""
        try:
            _, flags, positionals = parse_cli_args(
                args,
                bool_flags={"--all"},
                aliases={"-a": "--all"},
            )
            if positionals:
                raise ValueError(f"Argumento inesperado em ps/process_status: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        show_all = "--all" in flags
        processes = self.kernel.process_manager.list_processes(active_only=not show_all)
        all_processes = self.kernel.process_manager.list_processes(active_only=False)
        terminated_hidden = sum(
            1 for p in all_processes if ProcessState.normalize(p.state) == ProcessState.TERMINATED
        )

        lines = [
            "======================================================================================",
            f"            LISTA DE PROCESSOS E THREADS (Relógio Lógico: {self.kernel.clock.now_ms} ms)",
            "======================================================================================",
            f"{'PID':<5} | {'Nome':<18} | {'Tipo':<8} | {'Estado':<10} | {'Prio':<4} | {'CPU (ms)':<12} | {'Bloqueio'}",
            "-" * 86,
        ]
        for proc in sorted(processes, key=lambda p: p.pid):
            burst_str = (
                f"{proc.cpu_consumed_ms}/{sum(t.cpu_burst_ms for t in proc.threads.values()) or proc.cpu_burst_ms}"
            )
            blk_str = self._format_process_block_reason(proc)
            lines.append(
                f"{proc.pid:<5} | {proc.name[:18]:<18} | {proc.process_type.value:<8} | "
                f"{proc.state.value:<10} | {proc.priority:<4} | {burst_str:<12} | {blk_str}"
            )
            threads = sorted(proc.list_threads(active_only=not show_all), key=lambda t: t.tid)
            for t in threads:
                t_state = ProcessState.normalize(t.state).value
                extra = []
                if t_state == ProcessState.BLOCKED.value:
                    extra.append(f"Bloqueio={t.block_reason.value}({t.blocked_on or '-'})")
                if t.held_mutexes:
                    extra.append(f"Mutexes={','.join(t.held_mutexes)}")
                extra_str = f" | {' | '.join(extra)}" if extra else ""
                lines.append(
                    f"  └─ TID {t.tid:<3} ({t.name:<12}) | Estado: {t_state:<10} | "
                    f"Prio: {t.priority} | CPU: {t.cpu_consumed_ms}/{t.cpu_burst_ms}ms "
                    f"(Restante: {t.remaining_burst_ms}ms){extra_str}"
                )

        if not show_all and terminated_hidden > 0:
            lines.append("-" * 86)
            lines.append(
                f"Nota: {terminated_hidden} processo(s) encerrado(s) oculto(s). Use '--all' para exibir todos."
            )
        lines.append("======================================================================================")

        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={
                "clock_ms": self.kernel.clock.now_ms,
                "show_all": show_all,
                "total": len(processes),
                "processes": [p.to_dict() for p in processes],
            },
        )

    def cmd_process_admit(self, args: List[str]) -> CommandResult:
        """Admit a NEW process into READY (or schedule future arrival) via ExecutionEngine."""
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: process_admit --process <nome|pid>",
            )
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--process"},
                aliases={"-p": "--process", "--pid": "--process"},
            )
            identifier = values.get("--process") or (positionals[0] if positionals else None)
            if not identifier:
                raise ValueError("Informe o processo via '--process <nome|pid>'.")
            if "--process" in values and positionals:
                raise ValueError(f"Argumento inesperado: '{positionals[0]}'.")
            proc = self.kernel.execution_engine.admit_process(identifier)
        except Exception as exc:
            return self._handle_exception(exc)

        now_ms = self.kernel.clock.now_ms
        if ProcessState.normalize(proc.state) == ProcessState.NEW and proc.arrival_time_ms > now_ms:
            status_desc = f"Chegada agendada para t={proc.arrival_time_ms} ms (atual: {now_ms} ms)"
        else:
            status_desc = "Admitido na fila de prontos (READY)"

        lines = [
            "[process_admit] Processo admitido com sucesso.",
            f"PID            : {proc.pid}",
            f"Nome           : {proc.name}",
            f"Estado Atual   : {proc.state.value}",
            f"Prioridade     : {proc.priority}",
            f"Chegada        : {proc.arrival_time_ms} ms",
            f"Situação       : {status_desc}",
        ]
        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={
                "process": proc.to_dict(),
                "state": proc.state.value,
                "clock_ms": now_ms,
            },
        )

    def cmd_thread_create(self, args: List[str]) -> CommandResult:
        """Create a schedulable SimulatedThread attached to an existing process."""
        if not args:
            return CommandResult(
                success=False,
                error=(
                    "Sintaxe: thread_create --process <nome|pid> --name <tname> "
                    "[--priority <int>] [--burst <ms>] [--arrival <ms>] "
                    "[--io-profile <none|fixed|periodic|random>] [--io-every <ms>] "
                    "[--io-duration <ms>] [--seed <int>] [--pages <p0,p1,...>]"
                ),
            )
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={
                    "--process",
                    "--name",
                    "--priority",
                    "--burst",
                    "--arrival",
                    "--io-profile",
                    "--io-every",
                    "--io-duration",
                    "--seed",
                    "--pages",
                },
                aliases={"-p": "--process", "--pid": "--process", "-n": "--name"},
            )
            proc_id = values.get("--process") or (positionals[0] if len(positionals) > 0 else None)
            tname = values.get("--name") or (positionals[1] if len(positionals) > 1 else None)
            if not proc_id or not tname:
                raise ValueError("Parâmetros obrigatórios ausentes: --process e --name são necessários.")

            priority = (
                parse_int_arg(values["--priority"], "Prioridade", min_val=1)
                if "--priority" in values
                else None
            )
            burst = (
                parse_int_arg(values["--burst"], "Burst de CPU", min_val=0)
                if "--burst" in values
                else 0
            )
            arrival = (
                parse_int_arg(values["--arrival"], "Tempo de chegada", min_val=0)
                if "--arrival" in values
                else None
            )
            io_every = (
                parse_int_arg(values["--io-every"], "Intervalo de E/S (--io-every)", min_val=1)
                if "--io-every" in values
                else None
            )
            io_duration = (
                parse_int_arg(values["--io-duration"], "Duração de E/S (--io-duration)", min_val=1)
                if "--io-duration" in values
                else None
            )
            seed_val = (
                parse_int_arg(values["--seed"], "Seed")
                if "--seed" in values
                else None
            )
            pages = (
                parse_pages_pattern(values["--pages"])
                if "--pages" in values
                else None
            )
            io_profile = build_io_profile(
                io_profile_str=values.get("--io-profile"),
                io_every=io_every,
                io_duration=io_duration,
                seed_val=seed_val,
                default_seed=self.kernel.execution_engine.default_seed,
            )

            thread = self.kernel.execution_engine.create_thread(
                process_identifier=proc_id,
                name=tname,
                priority=priority,
                cpu_burst_ms=burst,
                arrival_time_ms=arrival,
                io_profile=io_profile,
                memory_access_pattern=pages,
            )
            proc = self.kernel.process_manager.get_process(thread.pid)
        except Exception as exc:
            return self._handle_exception(exc)

        lines = [
            "[thread_create] Thread criada com sucesso.",
            f"TID            : {thread.tid}",
            f"Nome da Thread : {thread.name}",
            f"Processo Pai   : {proc.name} (PID {proc.pid})",
            f"Estado         : {thread.state.value}",
            f"Prioridade     : {thread.priority}",
            f"Burst de CPU   : {thread.cpu_burst_ms} ms",
            f"Chegada        : {thread.arrival_time_ms} ms",
            f"Perfil de E/S  : {describe_io_profile(io_profile)}",
        ]
        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={"thread": thread.to_dict(), "process_pid": proc.pid},
        )

    def cmd_thread_status(self, args: List[str]) -> CommandResult:
        """Display detailed status of simulated threads globally or for a given process."""
        try:
            values, flags, positionals = parse_cli_args(
                args,
                value_flags={"--process"},
                bool_flags={"--active"},
                aliases={"-p": "--process", "--pid": "--process"},
            )
            proc_id = values.get("--process") or (positionals[0] if positionals else None)
            if "--process" in values and positionals:
                raise ValueError(f"Argumento inesperado: '{positionals[0]}'.")
            active_only = "--active" in flags
            threads = self.kernel.process_manager.list_threads(
                process_identifier=proc_id,
                active_only=active_only,
            )
        except Exception as exc:
            return self._handle_exception(exc)

        threads_sorted = sorted(threads, key=lambda t: t.tid)
        lines = [
            "======================================================================================",
            f"                STATUS DAS THREADS SIMULADAS (Relógio: {self.kernel.clock.now_ms} ms)",
            "======================================================================================",
        ]
        if not threads_sorted:
            lines.append("Nenhuma thread registrada para o filtro informado.")
            lines.append("======================================================================================")
            return CommandResult(
                success=True,
                output="\n".join(lines),
                data={"threads": [], "count": 0},
            )

        lines.append(
            f"{'TID':<5} | {'PID':<5} | {'Nome':<14} | {'Estado':<10} | {'Prio':<4} | "
            f"{'CPU':<10} | {'Quantum':<7} | {'Bloqueio / Mutexes'}"
        )
        lines.append("-" * 86)
        for t in threads_sorted:
            t_state = ProcessState.normalize(t.state).value
            cpu_str = f"{t.cpu_consumed_ms}/{t.cpu_burst_ms}ms"
            q_str = f"{t.quantum_used_ms}ms"
            info_parts = []
            if t_state == ProcessState.BLOCKED.value:
                info_parts.append(f"{t.block_reason.value}:{t.blocked_on or '-'}")
            if t.held_mutexes:
                info_parts.append(f"held=[{','.join(t.held_mutexes)}]")
            info_str = " | ".join(info_parts) if info_parts else "-"
            lines.append(
                f"{t.tid:<5} | {t.pid:<5} | {t.name[:14]:<14} | {t_state:<10} | "
                f"{t.priority:<4} | {cpu_str:<10} | {q_str:<7} | {info_str}"
            )
        lines.append("======================================================================================")

        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={"threads": [t.to_dict() for t in threads_sorted], "count": len(threads_sorted)},
        )

    def cmd_sched_config(self, args: List[str]) -> CommandResult:
        """Inspect or update CPU scheduler algorithm, quantum, and default RNG seed."""
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--algorithm", "--quantum", "--seed"},
                aliases={"--alg": "--algorithm", "-a": "--algorithm", "-q": "--quantum", "-s": "--seed"},
            )
            if positionals:
                raise ValueError(f"Argumento posicional inesperado: '{positionals[0]}'.")

            if not values:
                lines = [
                    "======================================================================",
                    "           CONFIGURAÇÃO DO ESCALONADOR DE CPU (ETAPA 5)",
                    "======================================================================",
                    "Algoritmo Ativo              : priority_rr (Prioridade + Round-Robin)",
                    f"Quantum Round-Robin          : {self.kernel.cpu_scheduler.quantum_ms} ms",
                    f"Seed Determinística Padrão   : {self.kernel.execution_engine.default_seed}",
                    f"Overhead Troca de Contexto   : {self.kernel.cpu_scheduler.context_switch_overhead_ms} ms",
                    "======================================================================",
                ]
                return CommandResult(
                    success=True,
                    output="\n".join(lines),
                    data={
                        "algorithm": "priority_rr",
                        "quantum_ms": self.kernel.cpu_scheduler.quantum_ms,
                        "default_seed": self.kernel.execution_engine.default_seed,
                    },
                )

            if "--algorithm" in values:
                alg = values["--algorithm"].strip().lower().replace("-", "_")
                if alg not in ("priority_rr", "priority_round_robin", "priority+rr"):
                    raise ValueError(
                        f"Algoritmo de escalonamento inválido: '{values['--algorithm']}'. "
                        "Algoritmo suportado: priority_rr."
                    )

            new_quantum: Optional[int] = None
            if "--quantum" in values:
                new_quantum = parse_int_arg(values["--quantum"], "Quantum", min_val=1)

            new_seed: Optional[int] = None
            if "--seed" in values:
                new_seed = parse_int_arg(values["--seed"], "Seed")

            if new_quantum is not None:
                self.kernel.execution_engine.set_quantum(new_quantum)
            if new_seed is not None:
                self.kernel.execution_engine.set_default_seed(new_seed)
        except Exception as exc:
            return self._handle_exception(exc)

        lines = [
            "[sched_config] Configuração do escalonador atualizada com sucesso.",
            "Algoritmo Ativo            : priority_rr (Prioridade + Round-Robin)",
            f"Quantum Round-Robin        : {self.kernel.cpu_scheduler.quantum_ms} ms",
            f"Seed Determinística Padrão : {self.kernel.execution_engine.default_seed}",
        ]
        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={
                "algorithm": "priority_rr",
                "quantum_ms": self.kernel.cpu_scheduler.quantum_ms,
                "default_seed": self.kernel.execution_engine.default_seed,
            },
        )

    def cmd_sched_status(self, args: List[str]) -> CommandResult:
        """Display running thread, priority ready queues, blocked entities, and completed counts."""
        try:
            _, _, positionals = parse_cli_args(args)
            if positionals:
                raise ValueError(f"Argumento inesperado em sched_status: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        now_ms = self.kernel.clock.now_ms
        running = self.kernel.cpu_scheduler.get_running_thread()
        blocked_threads = self._get_blocked_threads()
        active_blocks = {
            rec.tid: rec for rec in self.kernel.syscall_dispatcher.block_registry.get_active_blocks()
        }
        user_procs = [p for p in self.kernel.process_manager.list_processes() if p.pid != 0]
        completed_procs = sum(
            1 for p in user_procs if ProcessState.normalize(p.state) == ProcessState.TERMINATED
        )
        completed_threads = sum(
            1
            for t in self.kernel.process_manager.list_threads()
            if ProcessState.normalize(t.state) == ProcessState.TERMINATED
        )

        lines = [
            f"Relógio Lógico Atual : {now_ms} ms",
            self.kernel.cpu_scheduler.format_queues(),
            f"Entidades Bloqueadas ({len(blocked_threads)}):",
        ]
        if blocked_threads:
            for t in sorted(blocked_threads, key=lambda th: th.tid):
                rec = active_blocks.get(t.tid)
                exp_str = (
                    f", desbloqueio previsto em {rec.expected_unblock_at_ms}ms"
                    if rec and rec.expected_unblock_at_ms is not None
                    else ""
                )
                lines.append(
                    f"  - TID {t.tid} '{t.name}' (PID {t.pid}): {t.block_reason.value} "
                    f"[{t.blocked_on or '-'}]{exp_str}"
                )
        else:
            lines.append("  Nenhuma entidade bloqueada.")

        lines.extend([
            f"Processos Concluídos : {completed_procs} / {len(user_procs)}",
            f"Threads Concluídas   : {completed_threads}",
            f"Eventos Pendentes    : {len(self.kernel.event_manager)}",
        ])

        status = self.kernel.execution_engine.get_status()
        status["blocked_entities"] = [t.to_dict() for t in blocked_threads]
        status["completed_processes"] = completed_procs
        status["completed_threads"] = completed_threads
        status["running_tid"] = running.tid if running is not None else None
        return CommandResult(success=True, output="\n".join(lines), data=status)

    def cmd_sched_step(self, args: List[str]) -> CommandResult:
        """Advance discrete-event simulation by --ms milliseconds (default 1)."""
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--ms"},
                aliases={"-m": "--ms"},
            )
            raw_ms = values.get("--ms") or (positionals[0] if positionals else None)
            if "--ms" in values and positionals:
                raise ValueError(f"Argumento inesperado: '{positionals[0]}'.")
            ms = parse_int_arg(raw_ms, "Passos (--ms)", min_val=0) if raw_ms is not None else 1
            res = self.kernel.execution_engine.step(ms)
        except Exception as exc:
            return self._handle_exception(exc)

        running = self.kernel.cpu_scheduler.get_running_thread()
        running_desc = (
            f"TID {running.tid} '{running.name}' (PID {running.pid}, restante {running.remaining_burst_ms}ms)"
            if running is not None
            else "Nenhuma (CPU ociosa)"
        )
        lines = [
            f"[sched_step] Simulação avançada de {res['start_ms']} ms para {res['end_ms']} ms "
            f"(+{res['elapsed_ms']} ms).",
            f"Motivo de Parada  : {self._format_run_stop_reason(res['stop_reason'])}",
            f"Em Execução       : {running_desc}",
            f"Prontas na Fila   : {res['ready_count']}",
            f"Eventos Pendentes : {res['pending_events']}",
        ]
        return CommandResult(success=True, output="\n".join(lines), data=res)

    def cmd_sched_run(self, args: List[str]) -> CommandResult:
        """Run discrete-event simulation until completion or optional stop conditions."""
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--max-ms", "--until-process", "--until-event"},
            )
            if positionals:
                raise ValueError(f"Argumento posicional inesperado: '{positionals[0]}'.")

            max_ms = (
                parse_int_arg(values["--max-ms"], "Limite (--max-ms)", min_val=0)
                if "--max-ms" in values
                else None
            )
            until_process = values.get("--until-process")
            until_event: Optional[SimulationEventType] = None
            if "--until-event" in values:
                raw_ev = values["--until-event"].strip().upper()
                try:
                    until_event = SimulationEventType(raw_ev)
                except ValueError as exc:
                    raise ValueError(
                        f"Tipo de evento inválido: '{values['--until-event']}'. "
                        f"Opções válidas: {self._validate_supported_event_names()}."
                    ) from exc

            res = self.kernel.execution_engine.run(
                max_ms=max_ms,
                until_process=until_process,
                until_event=until_event,
            )
        except Exception as exc:
            return self._handle_exception(exc)

        m = res["metrics"]
        lines = [
            "[sched_run] Execução da simulação finalizada.",
            f"Intervalo         : {res['start_ms']} ms -> {res['end_ms']} ms ({res['elapsed_ms']} ms)",
            f"Motivo de Parada  : {self._format_run_stop_reason(res['stop_reason'])}",
            f"Processos         : {m['completed_processes']} / {m['total_processes']} concluídos",
            f"Utilização da CPU : {m['cpu_utilization_pct']:.2f}% (Ocupada: {m['cpu_busy_ms']} ms, Ociosa: {m['idle_time_ms']} ms)",
            f"Trocas Contexto   : {m['context_switches_total']}",
        ]
        return CommandResult(success=True, output="\n".join(lines), data=res)

    def cmd_process_syscall(self, args: List[str]) -> CommandResult:
        """Schedule or immediately execute a simulated syscall on a process/thread."""
        if not args:
            return CommandResult(
                success=False,
                error=(
                    "Sintaxe: process_syscall --process <nome|pid> [--thread <tname|tid>] "
                    "--type <io_read|io_write|fs_read|fs_write|sleep|yield|mutex_lock|"
                    "mutex_unlock|memory_load|memory_write|exit> [--at-cpu <ms>] "
                    "[--duration <ms>] [--block <id>] [--path <p>] [--data <txt>] "
                    "[--mutex <name>] [--page <n>] [--write] [--now]"
                ),
            )
        try:
            values, flags, positionals = parse_cli_args(
                args,
                value_flags={
                    "--process",
                    "--thread",
                    "--type",
                    "--at-cpu",
                    "--duration",
                    "--block",
                    "--path",
                    "--data",
                    "--mutex",
                    "--page",
                },
                bool_flags={"--write", "--now"},
                aliases={"-p": "--process", "--pid": "--process", "-t": "--thread", "--tid": "--thread"},
            )
            if positionals:
                raise ValueError(f"Argumento posicional inesperado: '{positionals[0]}'.")

            proc_id = values.get("--process")
            raw_type = values.get("--type")
            if not proc_id or not raw_type:
                raise ValueError("Parâmetros obrigatórios ausentes: --process e --type são necessários.")

            syscall_type = SyscallType.from_string(raw_type)
            now_mode = "--now" in flags
            if now_mode and "--at-cpu" in values:
                raise ValueError("Os parâmetros '--now' e '--at-cpu' são mutuamente exclusivos.")

            duration_ms = (
                parse_int_arg(values["--duration"], "Duração (--duration)", min_val=0)
                if "--duration" in values
                else 0
            )
            block_id = (
                parse_int_arg(values["--block"], "Bloco (--block)", min_val=0)
                if "--block" in values
                else None
            )
            logical_page = (
                parse_int_arg(values["--page"], "Página (--page)", min_val=0)
                if "--page" in values
                else None
            )
            path = values.get("--path")
            data_txt = values.get("--data")
            mutex_name = values.get("--mutex")
            thread_id = values.get("--thread")
            is_write = "--write" in flags

            if syscall_type in (SyscallType.FS_READ, SyscallType.FS_WRITE) and (not path or not path.strip()):
                raise ValueError(f"Syscall '{syscall_type.value}' requer '--path <caminho>'.")
            if syscall_type in (SyscallType.MUTEX_LOCK, SyscallType.MUTEX_UNLOCK) and (
                not mutex_name or not mutex_name.strip()
            ):
                raise ValueError(f"Syscall '{syscall_type.value}' requer '--mutex <nome>'.")

            if now_mode:
                outcome = self.kernel.execution_engine.execute_syscall_now(
                    process_identifier=proc_id,
                    syscall_type=syscall_type,
                    duration_ms=duration_ms,
                    thread_identifier=thread_id,
                    block_id=block_id,
                    path=path,
                    data=data_txt,
                    mutex_name=mutex_name,
                    logical_page=logical_page,
                    is_write=is_write,
                )
                proc = self.kernel.process_manager.get_process(proc_id)
                lines = [
                    "[process_syscall] Syscall executada imediatamente.",
                    f"Processo      : {proc.name} (PID {proc.pid})",
                    f"Syscall       : {syscall_type.value}",
                    f"Bloqueou      : {'SIM' if outcome.get('blocked') else 'NÃO'}",
                    f"Estado Thread : {outcome.get('thread_state')}",
                ]
                return CommandResult(success=True, output="\n".join(lines), data=outcome)

            if "--at-cpu" in values:
                trigger_cpu = parse_int_arg(values["--at-cpu"], "Gatilho de CPU (--at-cpu)", min_val=0)
            else:
                proc = self.kernel.process_manager.get_process(proc_id)
                if thread_id is not None:
                    th = self.kernel.process_manager.get_thread(thread_id, process_identifier=proc)
                    trigger_cpu = th.cpu_consumed_ms
                elif proc.threads:
                    first_th = proc.get_thread("main") or next(iter(proc.threads.values()))
                    trigger_cpu = first_th.cpu_consumed_ms
                else:
                    trigger_cpu = 0

            step = self.kernel.execution_engine.schedule_syscall(
                process_identifier=proc_id,
                syscall_type=syscall_type,
                trigger_cpu_ms=trigger_cpu,
                duration_ms=duration_ms,
                thread_identifier=thread_id,
                block_id=block_id,
                path=path,
                data=data_txt,
                mutex_name=mutex_name,
                logical_page=logical_page,
                is_write=is_write,
            )
            proc = self.kernel.process_manager.get_process(proc_id)
        except Exception as exc:
            return self._handle_exception(exc)

        lines = [
            "[process_syscall] Syscall agendada com sucesso.",
            f"Processo      : {proc.name} (PID {proc.pid})",
            f"Syscall       : {step.syscall_type.value}",
            f"Gatilho (CPU) : {step.trigger_cpu_ms} ms consumidos",
            f"Duração       : {step.duration_ms} ms",
        ]
        if step.block_id is not None:
            lines.append(f"Bloco         : {step.block_id}")
        if step.path is not None:
            lines.append(f"Caminho       : {step.path}")
        if step.mutex_name is not None:
            lines.append(f"Mutex         : {step.mutex_name}")
        if step.logical_page is not None:
            lines.append(f"Página Lógica : {step.logical_page}")
        return CommandResult(success=True, output="\n".join(lines), data={"step": step.to_dict()})

    def cmd_mutex_create(self, args: List[str]) -> CommandResult:
        """Create a named synchronization mutex."""
        if not args:
            return CommandResult(success=False, error="Sintaxe: mutex_create [--name] <nome>")
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--name"},
                aliases={"-n": "--name"},
            )
            name = values.get("--name") or (positionals[0] if positionals else None)
            if not name:
                raise ValueError("Informe o nome do mutex.")
            if "--name" in values and positionals:
                raise ValueError(f"Argumento inesperado: '{positionals[0]}'.")
            mutex = self.kernel.sync_manager.create_mutex(name)
        except Exception as exc:
            return self._handle_exception(exc)

        return CommandResult(
            success=True,
            output=f"[mutex_create] Mutex '{mutex.name}' criado com sucesso (estado: LIVRE).",
            data={"mutex": mutex.to_dict()},
        )

    def _run_mutex_op(self, args: List[str], op_type: SyscallType) -> CommandResult:
        verb = "mutex_lock" if op_type == SyscallType.MUTEX_LOCK else "mutex_unlock"
        if not args:
            return CommandResult(
                success=False,
                error=f"Sintaxe: {verb} --mutex <nome> --process <nome|pid> [--thread <tname|tid>]",
            )
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--mutex", "--process", "--thread"},
                aliases={
                    "-m": "--mutex",
                    "--name": "--mutex",
                    "-p": "--process",
                    "--pid": "--process",
                    "-t": "--thread",
                    "--tid": "--thread",
                },
            )
            if positionals:
                raise ValueError(f"Argumento posicional inesperado: '{positionals[0]}'.")

            mutex_name = values.get("--mutex")
            proc_id = values.get("--process")
            thread_id = values.get("--thread")
            if not mutex_name or not proc_id:
                raise ValueError(f"Parâmetros obrigatórios ausentes em {verb}: --mutex e --process.")

            outcome = self.kernel.execution_engine.execute_syscall_now(
                process_identifier=proc_id,
                syscall_type=op_type,
                thread_identifier=thread_id,
                mutex_name=mutex_name,
            )
            mutex = self.kernel.sync_manager.get_mutex(mutex_name)
        except Exception as exc:
            return self._handle_exception(exc)

        if op_type == SyscallType.MUTEX_LOCK:
            if outcome.get("acquired"):
                msg = (
                    f"[mutex_lock] Mutex '{mutex.name}' adquirido com sucesso "
                    f"(dono: TID {mutex.owner_tid}, estado thread: {outcome.get('thread_state')})."
                )
            else:
                msg = (
                    f"[mutex_lock] Contenção no mutex '{mutex.name}': thread bloqueada na fila FIFO "
                    f"(dono atual: TID {mutex.owner_tid}, fila: {list(mutex.wait_queue)})."
                )
        else:
            woken_tid = outcome.get("woken_tid")
            if woken_tid is not None:
                msg = (
                    f"[mutex_unlock] Mutex '{mutex.name}' liberado e transferido (handoff FIFO) "
                    f"para TID {woken_tid}."
                )
            else:
                msg = f"[mutex_unlock] Mutex '{mutex.name}' liberado com sucesso (estado: LIVRE)."

        outcome["mutex"] = mutex.to_dict()
        return CommandResult(success=True, output=msg, data=outcome)

    def cmd_mutex_lock(self, args: List[str]) -> CommandResult:
        """Acquire a mutex immediately on behalf of a process/thread."""
        return self._run_mutex_op(args, SyscallType.MUTEX_LOCK)

    def cmd_mutex_unlock(self, args: List[str]) -> CommandResult:
        """Release a held mutex immediately on behalf of a process/thread."""
        return self._run_mutex_op(args, SyscallType.MUTEX_UNLOCK)

    def cmd_mutex_status(self, args: List[str]) -> CommandResult:
        """Display status of all mutexes, owners, FIFO wait queues, and deadlocks."""
        try:
            _, _, positionals = parse_cli_args(args)
            if positionals:
                raise ValueError(f"Argumento inesperado em mutex_status: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        report = self.kernel.sync_manager.format_status()
        status_data = self.kernel.sync_manager.get_status()
        return CommandResult(success=True, output=report, data=status_data)

    def cmd_mutex_demo(self, args: List[str]) -> CommandResult:
        """Execute the Buffer_Video producer/consumer mutual exclusion demonstration."""
        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--scenario", "--quantum"},
                aliases={"-q": "--quantum"},
            )
            if positionals:
                raise ValueError(f"Argumento inesperado em mutex_demo: '{positionals[0]}'.")

            scenario = values.get("--scenario", "buffer_video").strip().lower()
            if scenario not in ("buffer_video", "buffer-video"):
                raise ValueError(
                    f"Cenário de demonstração inválido: '{values['--scenario']}'. "
                    "Cenário suportado: buffer_video."
                )

            quantum = (
                parse_int_arg(values["--quantum"], "Quantum", min_val=1)
                if "--quantum" in values
                else 2
            )
            demo = self.kernel.execution_engine.run_buffer_video_demo(quantum_ms=quantum)
        except Exception as exc:
            return self._handle_exception(exc)

        m = demo["mutex"]
        t1 = demo["t1"]
        t2 = demo["t2"]
        disjoint_str = (
            "SIM (seções críticas disjuntas, zero condição de corrida)"
            if demo["critical_sections_disjoint"]
            else "NÃO (violação de exclusão mútua)"
        )
        lines = [
            "======================================================================",
            "           DEMONSTRAÇÃO DE CONCORRÊNCIA E MUTEX — BUFFER_VIDEO",
            "======================================================================",
            f"Cenário              : {m['name']} (Processo '{demo['process']['name']}', PID {demo['process']['pid']})",
            f"Quantum Configurado  : {demo['quantum_ms']} ms",
            f"Exclusão Mútua       : {disjoint_str}",
            f"Mutex '{m['name']}'  : locked={m['locked']} | aquisições={m['acquire_count']} | "
            f"liberações={m['release_count']} | contenções={m['contention_count']}",
            "----------------------------------------------------------------------",
            f"Thread {t1['name']} (TID {t1['tid']}): estado={t1['state']} | CPU={t1['cpu_consumed_ms']}ms | "
            f"espera={t1['total_wait_ms']}ms | bloqueado={t1['total_blocked_ms']}ms | fim={t1['finish_time_ms']}ms",
            f"Thread {t2['name']} (TID {t2['tid']}): estado={t2['state']} | CPU={t2['cpu_consumed_ms']}ms | "
            f"espera={t2['total_wait_ms']}ms | bloqueado={t2['total_blocked_ms']}ms | fim={t2['finish_time_ms']}ms",
            "----------------------------------------------------------------------",
            "Eventos do Mutex:",
        ]
        for entry in m["history"]:
            lines.append(
                f"  [t={entry['timestamp_ms']:>2}ms] {entry['event']:<10} | {entry['details']}"
            )
        lines.append("======================================================================")

        return CommandResult(success=True, output="\n".join(lines), data=demo)

    def cmd_deadlock_check(self, args: List[str]) -> CommandResult:
        """Run Wait-For Graph deadlock cycle detection and no-progress stall diagnostics."""
        try:
            _, _, positionals = parse_cli_args(args)
            if positionals:
                raise ValueError(f"Argumento inesperado em deadlock_check: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        cycles = self.kernel.sync_manager.detect_deadlocks()
        has_running = self.kernel.cpu_scheduler.get_running_thread() is not None
        has_ready = not self.kernel.cpu_scheduler.is_ready_empty()
        has_pending = not self.kernel.event_manager.is_empty()
        no_progress = self.kernel.sync_manager.check_no_progress(
            has_ready=has_ready,
            has_running=has_running,
            has_pending_events=has_pending,
        )
        blocked_threads = self._get_blocked_threads()

        deadlock_detected = bool(cycles) or bool(no_progress and no_progress.get("deadlock_detected"))
        stalled = bool(no_progress and no_progress.get("stalled"))

        lines = [
            "======================================================================",
            "          VERIFICAÇÃO DE DEADLOCK E ESTAGNAÇÃO (WAIT-FOR GRAPH)",
            "======================================================================",
            f"Mutexes Registrados : {len(self.kernel.sync_manager.mutexes)}",
            f"Threads Bloqueadas  : {len(blocked_threads)}",
        ]
        if deadlock_detected:
            lines.append("Status              : DEADLOCK DETECTADO")
            for idx, cycle in enumerate(cycles, start=1):
                lines.append(f"  Ciclo #{idx}: {' ; '.join(cycle)}")
            if no_progress:
                lines.append(f"Diagnóstico         : {no_progress['message']}")
        elif stalled and no_progress is not None:
            lines.append("Status              : ESTAGNAÇÃO DETECTADA (No-Progress)")
            lines.append(f"Diagnóstico         : {no_progress['message']}")
        else:
            lines.append("Status              : SAUDÁVEL (Nenhum deadlock ou estagnação detectada)")
        lines.append("======================================================================")

        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={
                "deadlock_detected": deadlock_detected,
                "stalled": stalled,
                "cycles": cycles,
                "no_progress": no_progress,
                "blocked_tids": [t.tid for t in blocked_threads],
            },
        )

    def cmd_memory_frames(self, args: List[str]) -> CommandResult:
        """Display live physical RAM frames synchronized with Stage 4 MemoryManager."""
        try:
            _, _, positionals = parse_cli_args(args)
            if positionals:
                raise ValueError(f"Argumento inesperado em memory_frames: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        frames_summary = self.kernel.execution_engine.get_frames_summary()
        report = self.kernel.metrics_collector.format_frames_summary(
            memory_manager=self.kernel.memory_manager,
            frames_summary=frames_summary,
        )
        return CommandResult(
            success=True,
            output=report,
            data={
                "frames": frames_summary,
                "occupied_count": sum(1 for f in frames_summary if f["occupied"]),
                "total_frames": len(frames_summary),
                "algorithm": self.kernel.memory_manager.algorithm.value,
            },
        )

    def cmd_sim_metrics(self, args: List[str]) -> CommandResult:
        """Display per-process, per-thread, and global Stage 5 execution metrics."""
        try:
            _, _, positionals = parse_cli_args(args)
            if positionals:
                raise ValueError(f"Argumento inesperado em sim_metrics: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        metrics = self.kernel.execution_engine.get_metrics()
        report = self.kernel.metrics_collector.format_metrics_report(simulation_metrics=metrics)
        return CommandResult(success=True, output=report, data=metrics.to_dict())

    def cmd_sim_timeline(self, args: List[str]) -> CommandResult:
        """Display chronological event timeline and/or CPU Gantt chart."""
        try:
            values, flags, positionals = parse_cli_args(
                args,
                value_flags={"--limit"},
                bool_flags={"--gantt"},
                aliases={"-l": "--limit", "-g": "--gantt"},
            )
            if positionals:
                raise ValueError(f"Argumento inesperado em sim_timeline: '{positionals[0]}'.")
            limit = (
                parse_int_arg(values["--limit"], "Limite (--limit)", min_val=0)
                if "--limit" in values
                else None
            )
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        show_gantt = "--gantt" in flags
        timeline_text = self.kernel.metrics_collector.format_timeline(limit=limit)
        timeline_entries = [e.to_dict() for e in self.kernel.execution_engine.get_timeline(limit=limit)]

        if show_gantt:
            gantt_text = self.kernel.metrics_collector.format_gantt()
            output = f"{timeline_text}\n\n{gantt_text}"
            gantt_slices = [s.to_dict() for s in self.kernel.execution_engine.get_gantt()]
        else:
            output = timeline_text
            gantt_slices = []

        return CommandResult(
            success=True,
            output=output,
            data={
                "timeline": timeline_entries,
                "gantt": gantt_slices,
                "count": len(timeline_entries),
            },
        )

    def cmd_sim_reset(self, args: List[str]) -> CommandResult:
        """Reset logical clock, scheduler queues, mutexes, metrics, and user processes/memory."""
        try:
            _, _, positionals = parse_cli_args(args)
            if positionals:
                raise ValueError(f"Argumento inesperado em sim_reset: '{positionals[0]}'.")
        except ValueError as exc:
            return CommandResult(success=False, error=str(exc))

        self.kernel.execution_engine.reset()
        lines = [
            "[sim_reset] Estado da simulação reiniciado com sucesso.",
            f"Relógio Lógico       : {self.kernel.clock.now_ms} ms",
            f"Processos Ativos     : {len(self.kernel.process_manager.list_processes())} (apenas Nucleo_Base PID 0)",
            f"Quantum Configurado  : {self.kernel.cpu_scheduler.quantum_ms} ms",
            f"Molduras Ocupadas    : {self.kernel.memory_manager.physical_memory.get_occupied_count()}",
        ]
        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={
                "clock_ms": self.kernel.clock.now_ms,
                "processes_count": len(self.kernel.process_manager.list_processes()),
            },
        )
