"""CLI command handlers and argument parser for OS Simulator."""

import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from os_simulator.cli.process_commands import (
    CommandResult,
    Stage5ProcessCommands,
    build_io_profile,
    describe_io_profile,
    parse_cli_args,
    parse_int_arg,
    parse_pages_pattern,
)
from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import OSSimulatorException, PageFaultException, PermissionDeniedException
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import AllocationStrategy, AuditEventType, PrivilegeMode, ProcessType, ReplacementAlgorithm
from os_simulator.security.crypto import decrypt_file, encrypt_file
from os_simulator.io.scheduler import (
    CSCANScheduler,
    FCFSScheduler,
    SCANScheduler,
    SSTFScheduler,
)
from os_simulator.io.ssd import WearLevelingMode
from os_simulator.storage.adapter import IOBlockDeviceAdapter
from os_simulator.storage.raid import RAIDFactory, RAIDLevel


def parse_size_string(size_str: str) -> int:
    """Parse size strings like '10KB', '512B', '1MB' into integer bytes."""
    clean = size_str.strip().upper()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)?$", clean)
    if not match:
        raise ValueError(f"Formato de tamanho inválido: '{size_str}'. Exemplos válidos: 10KB, 512B, 1MB.")
    val_num = float(match.group(1))
    unit = match.group(2) or "B"
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
    }
    return int(val_num * multipliers[unit])


def _fmt_kb(val: int) -> str:
    """Format integers with dot thousand separators (Portuguese locale standard: 1.024 KB)."""
    return f"{val:,}".replace(",", ".")


class CommandDispatcher:
    """Dispatches CLI commands to the appropriate kernel handlers."""

    def __init__(self, kernel: SimulationKernel):
        self.kernel = kernel
        self.process_commands = Stage5ProcessCommands(self.kernel)

    def execute_line(self, line: str) -> CommandResult:
        """Parse and execute a single CLI input line."""
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            return CommandResult(success=True)

        try:
            tokens = shlex.split(trimmed)
        except ValueError as e:
            return CommandResult(success=False, error=f"Erro de sintaxe na linha: {e}")

        cmd = tokens[0].lower()
        args = tokens[1:]

        handlers = {
            # Filesystem commands
            "mkdir": self.cmd_mkdir,
            "create": self.cmd_create,
            "write_file": self.cmd_write_file,
            "read_file": self.cmd_read_file,
            "delete_file": self.cmd_delete_file,
            "delete_directory": self.cmd_delete_directory,
            "rmdir": self.cmd_delete_directory,
            "rm": self.cmd_delete_file,
            "fs_status": self.cmd_fs_status,
            "ls": self.cmd_ls,
            "cd": self.cmd_cd,
            "pwd": self.cmd_pwd,
            "tree": self.cmd_tree,
            # I/O and Disk Scheduling commands
            "io_status": self.cmd_io_status,
            "io_scheduler": self.cmd_io_scheduler,
            "io_benchmark": self.cmd_io_benchmark,
            # SSD and Wear Leveling commands
            "ssd_status": self.cmd_ssd_status,
            # RAID commands
            "raid_status": self.cmd_raid_status,
            "raid_fail": self.cmd_raid_fail,
            "raid_rebuild": self.cmd_raid_rebuild,
            "raid_init": self.cmd_raid_init,
            # Security and Protection commands (Etapa 3)
            "login": self.cmd_login,
            "logout": self.cmd_logout,
            "whoami": self.cmd_whoami,
            "useradd": self.cmd_useradd,
            "userdel": self.cmd_userdel,
            "usermod": self.cmd_usermod,
            "groupadd": self.cmd_groupadd,
            "groupdel": self.cmd_groupdel,
            "groups": self.cmd_groups,
            "chmod": self.cmd_chmod,
            "chown": self.cmd_chown,
            "chgrp": self.cmd_chgrp,
            "security_status": self.cmd_security_status,
            "encrypt_file": self.cmd_encrypt_file,
            "decrypt_file": self.cmd_decrypt_file,
            "antivirus_scan": self.cmd_antivirus_scan,
            "integrity_check": self.cmd_integrity_check,
            "audit_log": self.cmd_audit_log,
            # Process and Memory management commands (Etapa 4)
            "create_process": self.cmd_create_process,
            "terminate_process": self.cmd_terminate_process,
            "memory_status": self.cmd_memory_status,
            "memory_compact": self.cmd_memory_compact,
            "translate_address": self.cmd_translate_address,
            "execute_step": self.cmd_execute_step,
            "page_replacement": self.cmd_page_replacement,
            "page_table": self.cmd_page_table,
            "memory_map": self.cmd_memory_map,
            # Process Scheduling, Threads, Syscalls, Concurrency & Metrics (Etapa 5)
            "ps": self.process_commands.cmd_ps,
            "process_status": self.process_commands.cmd_ps,
            "process_admit": self.process_commands.cmd_process_admit,
            "thread_create": self.process_commands.cmd_thread_create,
            "thread_status": self.process_commands.cmd_thread_status,
            "sched_config": self.process_commands.cmd_sched_config,
            "sched_status": self.process_commands.cmd_sched_status,
            "sched_step": self.process_commands.cmd_sched_step,
            "sched_run": self.process_commands.cmd_sched_run,
            "process_syscall": self.process_commands.cmd_process_syscall,
            "mutex_create": self.process_commands.cmd_mutex_create,
            "mutex_lock": self.process_commands.cmd_mutex_lock,
            "mutex_unlock": self.process_commands.cmd_mutex_unlock,
            "mutex_status": self.process_commands.cmd_mutex_status,
            "mutex_demo": self.process_commands.cmd_mutex_demo,
            "deadlock_check": self.process_commands.cmd_deadlock_check,
            "memory_frames": self.process_commands.cmd_memory_frames,
            "sim_metrics": self.process_commands.cmd_sim_metrics,
            "sim_timeline": self.process_commands.cmd_sim_timeline,
            "sim_reset": self.process_commands.cmd_sim_reset,
            # System Help
            "help": self.cmd_help,
        }

        handler = handlers.get(cmd)
        if not handler:
            return CommandResult(
                success=False,
                error=f"Comando não reconhecido: '{cmd}'. Digite 'help' para comandos disponíveis.",
            )

        try:
            return handler(args)
        except OSSimulatorException as e:
            return CommandResult(success=False, error=str(e))
        except Exception as e:
            return CommandResult(success=False, error=f"Erro inesperado: {str(e)}")

    def cmd_mkdir(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: mkdir <caminho_diretorio>")
        path = args[0]
        node = self.kernel.fs_service.mkdir(path, cwd=self.kernel.get_cwd(), context=self.kernel.context)
        return CommandResult(
            success=True,
            output=f"Diretório criado com sucesso: {node.get_path()}",
            data={"path": node.get_path(), "inode_id": node.inode_id},
        )

    def cmd_create(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: create <caminho_arquivo> [--size <tamanho>] [--strategy <contiguous|fat|indexed>]",
            )
        path = args[0]
        size_bytes = 0
        strategy: Optional[AllocationStrategy] = None

        idx = 1
        while idx < len(args):
            flag = args[idx]
            if flag == "--size" and idx + 1 < len(args):
                size_bytes = parse_size_string(args[idx + 1])
                idx += 2
            elif flag.startswith("--size="):
                size_bytes = parse_size_string(flag.split("=", 1)[1])
                idx += 1
            elif flag == "--strategy" and idx + 1 < len(args):
                strategy = AllocationStrategy.from_string(args[idx + 1])
                idx += 2
            elif flag.startswith("--strategy="):
                strategy = AllocationStrategy.from_string(flag.split("=", 1)[1])
                idx += 1
            else:
                idx += 1

        node = self.kernel.fs_service.create_file(
            path, size_bytes=size_bytes, strategy=strategy, cwd=self.kernel.get_cwd(), context=self.kernel.context
        )
        size_msg = f" com reserva de {size_bytes} bytes" if size_bytes > 0 else ""
        return CommandResult(
            success=True,
            output=f"Arquivo criado com sucesso: {node.get_path()}{size_msg}",
            data={"path": node.get_path(), "inode_id": node.inode_id, "size_bytes": size_bytes},
        )

    def cmd_write_file(self, args: List[str]) -> CommandResult:
        if len(args) < 2:
            return CommandResult(
                success=False,
                error='Sintaxe: write_file <caminho_arquivo> "<conteudo>" [--append]',
            )
        path = args[0]
        content = args[1]
        append = "--append" in args[2:]

        result = self.kernel.fs_service.write_file(
            path, content, append=append, cwd=self.kernel.get_cwd(), context=self.kernel.context
        )

        real_size = result["real_size"]
        real_kb = real_size / 1024.0
        allocated_capacity = result["allocated_capacity"]
        alloc_kb = allocated_capacity / 1024.0
        blocks = result["allocated_blocks"]
        index_b = result["index_block_id"]

        lines = [
            f"[write_file] Arquivo gravado com sucesso: {result['path']}",
            f"Tamanho Real do Conteúdo   : {real_size:,} bytes ({real_kb:,.2f} KB)".replace(",", "."),
            f"Blocos de Dados Alocados   : {len(blocks)} blocos ({blocks})",
        ]
        if index_b is not None:
            lines.append(f"Bloco de Índice Alocado    : Bloco {index_b}")
        lines.extend([
            f"Capacidade Total Alocada   : {allocated_capacity:,} bytes ({alloc_kb:,.2f} KB)".replace(",", "."),
            f"Fragmentação Interna       : {result['internal_fragmentation']:,} bytes".replace(",", "."),
            f"Fragmentação Externa       : {result['external_fragmentation']} bytes",
        ])

        return CommandResult(success=True, output="\n".join(lines), data=result)

    def cmd_read_file(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: read_file <caminho_arquivo>")
        path = args[0]
        content = self.kernel.fs_service.read_file(path, cwd=self.kernel.get_cwd(), context=self.kernel.context)
        return CommandResult(success=True, output=content, data={"content": content})

    def cmd_delete_file(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: delete_file <caminho_arquivo>")
        path = args[0]
        self.kernel.fs_service.delete_file(path, cwd=self.kernel.get_cwd(), context=self.kernel.context)
        return CommandResult(success=True, output=f"Arquivo excluído com sucesso: '{path}'.")

    def cmd_delete_directory(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: delete_directory <caminho_diretorio>")
        path = args[0]
        self.kernel.fs_service.delete_directory(path, cwd=self.kernel.get_cwd(), context=self.kernel.context)
        return CommandResult(success=True, output=f"Diretório excluído com sucesso: '{path}'.")

    def cmd_fs_status(self, args: List[str]) -> CommandResult:
        details = any(arg in ("--details", "--detailed") for arg in args)
        report = self.kernel.fs_service.format_fs_status(details=details)
        raw_status = self.kernel.fs_service.get_fs_status(details=details)
        return CommandResult(success=True, output=report, data=raw_status)

    def cmd_ls(self, args: List[str]) -> CommandResult:
        target_path = args[0] if args else self.kernel.get_cwd()
        dir_node = self.kernel.fs_service.vfs.get_directory(target_path, cwd=self.kernel.get_cwd())
        items = dir_node.list_children()
        if not items:
            return CommandResult(success=True, output="(diretório vazio)")
        lines = []
        for item in items:
            type_str = "[DIR]" if item.node_type == item.node_type.DIRECTORY else "[ARQ]"
            size_str = ""
            if item.inode_id in self.kernel.fs_service.inode_table:
                inode = self.kernel.fs_service.inode_table[item.inode_id]
                size_str = f" ({inode.file_size} bytes)"
            lines.append(f"{item.name}{size_str} {type_str}")
        return CommandResult(success=True, output="\n".join(lines))

    def cmd_cd(self, args: List[str]) -> CommandResult:
        target = args[0] if args else "/"
        new_cwd = self.kernel.set_cwd(target)
        return CommandResult(success=True, output=f"Diretório atual: {new_cwd}")

    def cmd_pwd(self, args: List[str]) -> CommandResult:
        return CommandResult(success=True, output=self.kernel.get_cwd())

    def cmd_tree(self, args: List[str]) -> CommandResult:
        tree_str = self.kernel.fs_service.get_tree_string()
        return CommandResult(success=True, output=tree_str)

    # =========================================================================
    # COMANDOS DE ENTRADA/SAÍDA (E/S) E ESCALONAMENTO DE DISCO
    # =========================================================================

    def cmd_io_status(self, args: List[str]) -> CommandResult:
        """Exibe o diagnóstico do subsistema de E/S e métricas de busca."""
        if self.kernel.io_manager is None:
            return CommandResult(
                success=False,
                error="Subsistema de E/S não está ativo ou dispositivo atual não utiliza IOManager.",
            )
        report = self.kernel.io_manager.format_io_status()
        metrics = self.kernel.io_manager.get_metrics_summary()
        return CommandResult(success=True, output=report, data=metrics)

    def cmd_io_scheduler(self, args: List[str]) -> CommandResult:
        """Consulta ou altera dinamicamente o algoritmo de escalonamento."""
        if self.kernel.io_manager is None:
            return CommandResult(
                success=False,
                error="Subsistema de E/S não está ativo ou dispositivo atual não utiliza IOManager.",
            )

        if not args:
            curr = self.kernel.io_manager.scheduler
            return CommandResult(
                success=True,
                output=f"Escalonador ativo: {curr.name} (Cabeça na trilha {curr.current_head})",
                data={"scheduler": curr.name, "head": curr.current_head},
            )

        target_alg = None
        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag == "--set" and idx + 1 < len(args):
                target_alg = args[idx + 1].strip().lower()
                idx += 2
            elif flag.startswith("--set="):
                target_alg = flag.split("=", 1)[1].strip().lower()
                idx += 1
            else:
                target_alg = flag.strip().lower()
                idx += 1

        schedulers_map = {
            "fcfs": FCFSScheduler,
            "sstf": SSTFScheduler,
            "scan": SCANScheduler,
            "cscan": CSCANScheduler,
            "c-scan": CSCANScheduler,
        }

        if target_alg not in schedulers_map:
            return CommandResult(
                success=False,
                error=(
                    f"Algoritmo de escalonamento inválido: '{target_alg}'. "
                    "Algoritmos válidos: fcfs, sstf, scan, cscan."
                ),
            )

        new_scheduler = schedulers_map[target_alg](
            initial_head=self.kernel.io_manager.scheduler.current_head
        )
        self.kernel.io_manager.set_scheduler(new_scheduler)
        return CommandResult(
            success=True,
            output=f"Escalonador de disco alterado com sucesso para: {new_scheduler.name}",
            data={"scheduler": new_scheduler.name},
        )

    def cmd_io_benchmark(self, args: List[str]) -> CommandResult:
        """Executa simulação de escalonamento ou comparação entre algoritmos."""
        alg: Optional[str] = None
        queue_str: str = "98,183,37,122,14"
        head: int = 53

        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag in ("--algorithm", "--alg") and idx + 1 < len(args):
                alg = args[idx + 1].strip().lower()
                idx += 2
            elif flag.startswith("--algorithm=") or flag.startswith("--alg="):
                alg = flag.split("=", 1)[1].strip().lower()
                idx += 1
            elif flag == "--queue" and idx + 1 < len(args):
                queue_str = args[idx + 1].strip()
                idx += 2
            elif flag.startswith("--queue="):
                queue_str = flag.split("=", 1)[1].strip()
                idx += 1
            elif flag == "--head" and idx + 1 < len(args):
                head = int(args[idx + 1])
                idx += 2
            elif flag.startswith("--head="):
                head = int(flag.split("=", 1)[1])
                idx += 1
            else:
                idx += 1

        try:
            tracks = [int(t.strip()) for t in queue_str.split(",") if t.strip()]
        except ValueError:
            return CommandResult(
                success=False,
                error=f"Formato inválido de fila de trilhas: '{queue_str}'. Exemplo: 98,183,37,122,14",
            )

        if not tracks:
            return CommandResult(success=False, error="A fila de trilhas não pode ser vazia.")

        schedulers_map = {
            "fcfs": FCFSScheduler,
            "sstf": SSTFScheduler,
            "scan": SCANScheduler,
            "cscan": CSCANScheduler,
            "c-scan": CSCANScheduler,
        }

        if alg:
            if alg not in schedulers_map:
                return CommandResult(
                    success=False,
                    error=f"Algoritmo inválido: '{alg}'. Opções: fcfs, sstf, scan, cscan.",
                )
            scheduler = schedulers_map[alg](initial_head=head)
            metrics = scheduler.schedule_tracks(tracks)
            return CommandResult(success=True, output=metrics.format_summary(), data={"metrics": metrics})

        # Run comparative benchmark across all 4 algorithms
        bench_scheds = [
            ("FCFS", FCFSScheduler(initial_head=head)),
            ("SSTF", SSTFScheduler(initial_head=head)),
            ("SCAN", SCANScheduler(initial_head=head)),
            ("C-SCAN", CSCANScheduler(initial_head=head)),
        ]

        results = []
        for name, sched in bench_scheds:
            m = sched.schedule_tracks(tracks)
            avg = m.total_seek_distance / len(tracks) if tracks else 0.0
            results.append((name, m.service_order, m.total_seek_distance, avg))

        # Sort by seek distance to find best
        best = min(results, key=lambda x: x[2])

        lines = [
            "========================================================================================",
            "                     BENCHMARK COMPARATIVO DE ESCALONAMENTO DE DISCO",
            "========================================================================================",
            f"Posição Inicial da Cabeça : Trilha {head}",
            f"Fila de Requisições       : {tracks} ({len(tracks)} requisições)",
            "----------------------------------------------------------------------------------------",
            f"{'Algoritmo':<10} {'Ordem de Atendimento':<35} {'Deslocamento (Trilhas)':<25} {'Média/Req'}",
            "----------------------------------------------------------------------------------------",
        ]
        for name, order, dist, avg in results:
            order_str = str(order)
            lines.append(f"{name:<10} {order_str:<35} {dist:<25} {avg:.2f}")
        lines.extend([
            "========================================================================================",
            f"Melhor Desempenho         : {best[0]} com {best[2]} trilhas percorridas (média {best[3]:.2f}/req)",
            "========================================================================================",
        ])

        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={"results": results, "best": best[0], "best_distance": best[2]},
        )

    # =========================================================================
    # COMANDOS DE SSD E WEAR LEVELING
    # =========================================================================

    def cmd_ssd_status(self, args: List[str]) -> CommandResult:
        """Exibe diagnóstico do SSD, FTL e Wear Leveling."""
        if self.kernel.ssd_device is None:
            return CommandResult(
                success=False,
                error="Dispositivo SSD não está configurado na simulação.",
            )

        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag == "--mode" and idx + 1 < len(args):
                m_str = args[idx + 1].strip().upper()
                if m_str in WearLevelingMode.__members__:
                    self.kernel.ssd_device.set_wear_mode(WearLevelingMode[m_str])
                idx += 2
            elif flag.startswith("--mode="):
                m_str = flag.split("=", 1)[1].strip().upper()
                if m_str in WearLevelingMode.__members__:
                    self.kernel.ssd_device.set_wear_mode(WearLevelingMode[m_str])
                idx += 1
            else:
                idx += 1

        report = self.kernel.ssd_device.format_wear_report()
        stats = self.kernel.ssd_device.get_wear_statistics()
        return CommandResult(success=True, output=report, data=stats)

    # =========================================================================
    # COMANDOS DE ARRANJO RAID
    # =========================================================================

    def cmd_raid_status(self, args: List[str]) -> CommandResult:
        """Exibe o status de saúde e configuração do arranjo RAID."""
        if self.kernel.raid_controller is None:
            return CommandResult(
                success=False,
                error="Arranjo RAID não está configurado na simulação.",
            )
        report = self.kernel.raid_controller.format_status()
        return CommandResult(
            success=True,
            output=report,
            data={
                "level": self.kernel.raid_controller.level.value,
                "status": self.kernel.raid_controller.status.value,
                "disks": len(self.kernel.raid_controller.disks),
                "online": self.kernel.raid_controller.online_disks_count,
            },
        )

    def cmd_raid_fail(self, args: List[str]) -> CommandResult:
        """Simula a falha de um disco físico no arranjo RAID."""
        if self.kernel.raid_controller is None:
            return CommandResult(
                success=False,
                error="Arranjo RAID não está configurado na simulação.",
            )
        if not args:
            return CommandResult(success=False, error="Sintaxe: raid_fail --disk <id_disco>")

        disk_id: Optional[int] = None
        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag == "--disk" and idx + 1 < len(args):
                try:
                    disk_id = int(args[idx + 1])
                except ValueError:
                    return CommandResult(success=False, error=f"ID do disco inválido: '{args[idx + 1]}'")
                idx += 2
            elif flag.startswith("--disk="):
                try:
                    disk_id = int(flag.split("=", 1)[1])
                except ValueError:
                    return CommandResult(success=False, error=f"ID do disco inválido: '{flag}'")
                idx += 1
            else:
                try:
                    disk_id = int(flag)
                except ValueError:
                    return CommandResult(success=False, error=f"ID do disco inválido: '{flag}'")
                idx += 1

        if disk_id is None:
            return CommandResult(success=False, error="Sintaxe: raid_fail --disk <id_disco>")

        try:
            self.kernel.raid_controller.fail_disk(disk_id)
            new_status = self.kernel.raid_controller.status.value
            return CommandResult(
                success=True,
                output=(
                    f"[RAID] Falha física injetada com sucesso no Disco #{disk_id:02d}.\n"
                    f"Estado atual do arranjo: {new_status}"
                ),
                data={"disk_id": disk_id, "status": new_status},
            )
        except Exception as exc:
            return CommandResult(success=False, error=str(exc))

    def cmd_raid_rebuild(self, args: List[str]) -> CommandResult:
        """Executa a reconstrução online de um disco falho no arranjo RAID."""
        if self.kernel.raid_controller is None:
            return CommandResult(
                success=False,
                error="Arranjo RAID não está configurado na simulação.",
            )
        if not args:
            return CommandResult(success=False, error="Sintaxe: raid_rebuild --disk <id_disco>")

        disk_id: Optional[int] = None
        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag == "--disk" and idx + 1 < len(args):
                try:
                    disk_id = int(args[idx + 1])
                except ValueError:
                    return CommandResult(success=False, error=f"ID do disco inválido: '{args[idx + 1]}'")
                idx += 2
            elif flag.startswith("--disk="):
                try:
                    disk_id = int(flag.split("=", 1)[1])
                except ValueError:
                    return CommandResult(success=False, error=f"ID do disco inválido: '{flag}'")
                idx += 1
            else:
                try:
                    disk_id = int(flag)
                except ValueError:
                    return CommandResult(success=False, error=f"ID do disco inválido: '{flag}'")
                idx += 1

        if disk_id is None:
            return CommandResult(success=False, error="Sintaxe: raid_rebuild --disk <id_disco>")

        try:
            self.kernel.raid_controller.rebuild_disk(disk_id)
            new_status = self.kernel.raid_controller.status.value
            return CommandResult(
                success=True,
                output=(
                    f"[RAID] Reconstrução dos dados do Disco #{disk_id:02d} concluída com sucesso.\n"
                    f"Estado atual do arranjo: {new_status}"
                ),
                data={"disk_id": disk_id, "status": new_status},
            )
        except Exception as exc:
            return CommandResult(success=False, error=str(exc))

    def cmd_raid_init(self, args: List[str]) -> CommandResult:
        """Inicializa um novo arranjo RAID na simulação."""
        level_str = "5"
        num_disks = 4
        disk_cap = 16

        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag == "--level" and idx + 1 < len(args):
                level_str = args[idx + 1].strip()
                idx += 2
            elif flag.startswith("--level="):
                level_str = flag.split("=", 1)[1].strip()
                idx += 1
            elif flag == "--disks" and idx + 1 < len(args):
                num_disks = int(args[idx + 1])
                idx += 2
            elif flag.startswith("--disks="):
                num_disks = int(flag.split("=", 1)[1])
                idx += 1
            elif flag == "--capacity" and idx + 1 < len(args):
                disk_cap = int(args[idx + 1])
                idx += 2
            elif flag.startswith("--capacity="):
                disk_cap = int(flag.split("=", 1)[1])
                idx += 1
            else:
                idx += 1

        level_map = {
            "0": RAIDLevel.RAID_0,
            "1": RAIDLevel.RAID_1,
            "4": RAIDLevel.RAID_4,
            "5": RAIDLevel.RAID_5,
            "raid0": RAIDLevel.RAID_0,
            "raid1": RAIDLevel.RAID_1,
            "raid4": RAIDLevel.RAID_4,
            "raid5": RAIDLevel.RAID_5,
        }

        if level_str.lower() not in level_map:
            return CommandResult(
                success=False,
                error=f"Nível de RAID inválido: '{level_str}'. Níveis suportados: 0, 1, 4, 5.",
            )

        level = level_map[level_str.lower()]
        try:
            new_raid = RAIDFactory.create(
                level=level,
                num_disks=num_disks,
                disk_capacity=disk_cap,
                block_size=self.kernel.device.block_size,
            )
            self.kernel.raid_controller = new_raid
            if self.kernel.io_manager is not None:
                self.kernel.io_manager.storage_backend = new_raid
            else:
                self.kernel.io_manager = IOManager(storage_backend=new_raid)
            self.kernel.device = IOBlockDeviceAdapter(
                io_manager=self.kernel.io_manager,
                logical_capacity=new_raid.logical_capacity,
                block_size=self.kernel.device.block_size,
            )
            self.kernel.fs_service.block_device = self.kernel.device

            lvl_label = level.value.replace("_", " ")
            return CommandResult(
                success=True,
                output=(
                    f"Arranjo {lvl_label} inicializado com sucesso ({num_disks} discos, "
                    f"capacidade útil: {new_raid.logical_capacity} blocos)."
                ),
            )
        except Exception as exc:
            return CommandResult(success=False, error=str(exc))

    # --------------------------------------------------------------------------
    # Security, Access Control and Protection Handlers (Etapa 3)
    # --------------------------------------------------------------------------
    def cmd_login(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(
                success=False, error="Sintaxe: login --user <nome> [--password <senha>]"
            )
        username = None
        password = ""
        idx = 0
        while idx < len(args):
            arg = args[idx]
            if arg == "--user" and idx + 1 < len(args):
                username = args[idx + 1]
                idx += 2
            elif arg.startswith("--user="):
                username = arg.split("=", 1)[1]
                idx += 1
            elif arg == "--password" and idx + 1 < len(args):
                password = args[idx + 1]
                idx += 2
            elif arg.startswith("--password="):
                password = arg.split("=", 1)[1]
                idx += 1
            elif not arg.startswith("-") and username is None:
                username = arg
                idx += 1
            elif not arg.startswith("-") and password == "":
                password = arg
                idx += 1
            else:
                idx += 1

        if not username:
            return CommandResult(
                success=False, error="Sintaxe: login --user <nome> [--password <senha>]"
            )

        new_ctx = self.kernel.auth_service.login(username, password)
        self.kernel.context = new_ctx
        mode_label = "MODO_KERNEL" if new_ctx.is_kernel_mode() else "MODO_USUARIO"
        output_msg = (
            f"Autenticado com sucesso.\n"
            f"Usuário: '{username}' | Grupo: '{new_ctx.primary_group}' | Modo: {mode_label}"
        )
        return CommandResult(
            success=True,
            output=output_msg,
            data={"username": username, "context": new_ctx},
        )

    def cmd_logout(self, args: List[str]) -> CommandResult:
        self.kernel.auth_service.logout(self.kernel.context)
        self.kernel.context = ExecutionContext(
            user_id=65534,
            username="nobody",
            groups=["nogroup"],
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd="/",
        )
        return CommandResult(success=True, output="Sessão encerrada com sucesso.")

    def cmd_whoami(self, args: List[str]) -> CommandResult:
        ctx = self.kernel.context
        mode_str = (
            "MODO_KERNEL (Anel 0)" if ctx.is_kernel_mode() else "MODO_USUARIO (Anel 3)"
        )
        lines = [
            f"Usuário Ativo        : {ctx.username} (UID: {ctx.user_id})",
            f"Grupos               : {', '.join(ctx.groups)}",
            f"Anel de Privilégio   : {mode_str}",
            f"Diretório de Trabalho: {ctx.cwd}",
        ]
        return CommandResult(
            success=True, output="\n".join(lines), data={"username": ctx.username}
        )

    def cmd_useradd(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: useradd <nome> [--group <grp>] [--groups <g1,g2>] [--password <senha>]",
            )
        username = args[0]
        primary_group = "users"
        supplementary: List[str] = []
        password = None

        idx = 1
        while idx < len(args):
            flag = args[idx]
            if flag == "--group" and idx + 1 < len(args):
                primary_group = args[idx + 1]
                idx += 2
            elif flag == "--groups" and idx + 1 < len(args):
                supplementary = [
                    g.strip() for g in args[idx + 1].split(",") if g.strip()
                ]
                idx += 2
            elif flag == "--password" and idx + 1 < len(args):
                password = args[idx + 1]
                idx += 2
            else:
                idx += 1

        self.kernel.user_manager.useradd(
            username=username,
            password=password,
            primary_group=primary_group,
            supplementary_groups=supplementary,
        )
        return CommandResult(
            success=True, output=f"Usuário '{username}' criado com sucesso."
        )

    def cmd_userdel(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: userdel <nome>")
        username = args[0]
        self.kernel.user_manager.userdel(username)
        return CommandResult(
            success=True, output=f"Usuário '{username}' removido com sucesso."
        )

    def cmd_groupadd(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: groupadd <nome>")
        group_name = args[0]
        self.kernel.user_manager.groupadd(group_name)
        return CommandResult(
            success=True, output=f"Grupo '{group_name}' criado com sucesso."
        )

    def cmd_groupdel(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: groupdel <nome>")
        group_name = args[0]
        self.kernel.user_manager.groupdel(group_name)
        return CommandResult(
            success=True, output=f"Grupo '{group_name}' removido com sucesso."
        )

    def cmd_usermod(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: usermod <nome> [--group <grp>] [--append-groups <g1,g2>] [--password <senha>]",
            )
        username = args[0]
        primary_group = None
        add_groups = None
        password = None
        idx = 1
        while idx < len(args):
            flag = args[idx]
            if flag in ("--group", "-g") and idx + 1 < len(args):
                primary_group = args[idx + 1]
                idx += 2
            elif flag.startswith("--group="):
                primary_group = flag.split("=", 1)[1]
                idx += 1
            elif flag in ("--append-groups", "-aG", "--groups") and idx + 1 < len(args):
                add_groups = [g.strip() for g in args[idx + 1].split(",") if g.strip()]
                idx += 2
            elif flag.startswith(("--append-groups=", "--groups=")):
                add_groups = [g.strip() for g in flag.split("=", 1)[1].split(",") if g.strip()]
                idx += 1
            elif flag == "--password" and idx + 1 < len(args):
                password = args[idx + 1]
                idx += 2
            elif flag.startswith("--password="):
                password = flag.split("=", 1)[1]
                idx += 1
            else:
                idx += 1

        self.kernel.user_manager.usermod(
            username=username,
            primary_group=primary_group,
            add_groups=add_groups,
            password=password,
        )
        return CommandResult(
            success=True, output=f"Usuário '{username}' modificado com sucesso."
        )

    def cmd_groups(self, args: List[str]) -> CommandResult:
        username = args[0] if args else self.kernel.context.username
        user = self.kernel.user_manager.get_user(username)
        if user is None:
            return CommandResult(
                success=False, error=f"Usuário '{username}' não encontrado."
            )
        groups_str = " ".join(user.groups)
        return CommandResult(
            success=True,
            output=f"{username} : {groups_str}",
            data={"username": username, "groups": user.groups},
        )

    def cmd_chmod(self, args: List[str]) -> CommandResult:
        if len(args) < 2:
            return CommandResult(
                success=False, error="Sintaxe: chmod <modo_octal> <caminho>"
            )
        mode = args[0]
        path = args[1]
        new_mode = self.kernel.security_manager.chmod(self.kernel.context, path, mode)
        return CommandResult(
            success=True,
            output=f"Permissões de '{path}' alteradas para {new_mode}.",
        )

    def cmd_chown(self, args: List[str]) -> CommandResult:
        if len(args) < 2:
            return CommandResult(
                success=False, error="Sintaxe: chown <dono>[:<grupo>] <caminho>"
            )
        owner_spec = args[0]
        path = args[1]
        if ":" in owner_spec:
            owner, group = owner_spec.split(":", 1)
            owner = owner if owner else None
            group = group if group else None
        else:
            owner = owner_spec
            group = None

        new_owner, new_group = self.kernel.security_manager.chown(
            self.kernel.context, path, owner=owner, group=group
        )
        return CommandResult(
            success=True,
            output=f"Propriedade de '{path}' alterada para {new_owner}:{new_group}.",
        )

    def cmd_chgrp(self, args: List[str]) -> CommandResult:
        if len(args) < 2:
            return CommandResult(
                success=False, error="Sintaxe: chgrp <grupo> <caminho>"
            )
        group = args[0]
        path = args[1]
        _, new_group = self.kernel.security_manager.chown(
            self.kernel.context, path, group=group
        )
        return CommandResult(
            success=True,
            output=f"Grupo de '{path}' alterado para '{new_group}'.",
        )

    def cmd_encrypt_file(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(
                success=False, error="Sintaxe: encrypt_file <caminho> [--key <chave>]"
            )
        path = args[0]
        key = "default_aes_key_simulated_32b!"
        idx = 1
        while idx < len(args):
            if args[idx] == "--key" and idx + 1 < len(args):
                key = args[idx + 1]
                idx += 2
            elif args[idx].startswith("--key="):
                key = args[idx].split("=", 1)[1]
                idx += 1
            else:
                idx += 1

        res = encrypt_file(
            self.kernel.fs_service, path, key, cwd=self.kernel.get_cwd()
        )
        lines = [
            f"[encrypt_file] Arquivo criptografado com sucesso: {path}",
            f"Algoritmo Criptográfico     : AES-256-GCM (Autenticado)",
            f"Tamanho Original (Plaintext) : {res['original_size']} bytes",
            f"Tamanho Cifrado (com Tag/IV) : {res['encrypted_size']} bytes",
            f"Blocos de Armazenamento      : {res['allocated_blocks']}",
        ]
        if res.get("allocated_blocks"):
            b0 = res["allocated_blocks"][0]
            raw_b0 = self.kernel.device.read_block(b0)
            hex_preview = "0x" + bytes(raw_b0[:16]).hex().upper() + "... (Encrypted Ciphertext)"
            lines.append("")
            lines.append("Conteúdo gravado nos blocos físicos:")
            lines.append(hex_preview)
        return CommandResult(success=True, output="\n".join(lines), data=res)

    def cmd_decrypt_file(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(
                success=False, error="Sintaxe: decrypt_file <caminho> [--key <chave>]"
            )
        path = args[0]
        key = "default_aes_key_simulated_32b!"
        idx = 1
        while idx < len(args):
            if args[idx] == "--key" and idx + 1 < len(args):
                key = args[idx + 1]
                idx += 2
            elif args[idx].startswith("--key="):
                key = args[idx].split("=", 1)[1]
                idx += 1
            else:
                idx += 1

        plaintext_bytes = decrypt_file(
            self.kernel.fs_service,
            path,
            key,
            in_place=True,
            cwd=self.kernel.get_cwd(),
        )
        return CommandResult(
            success=True,
            output=f"[decrypt_file] Arquivo '{path}' descriptografado com sucesso ({len(plaintext_bytes)} bytes restaurados).",
            data={"plaintext": plaintext_bytes},
        )

    def cmd_antivirus_scan(self, args: List[str]) -> CommandResult:
        path = args[0] if args else "/"
        report = self.kernel.antivirus_scanner.scan_path(
            path, context=self.kernel.context
        )
        report_text = report.format_report()
        return CommandResult(
            success=True, output=report_text, data={"report": report}
        )

    def cmd_integrity_check(self, args: List[str]) -> CommandResult:
        path = args[0] if args else "/"
        register = "--register" in args
        if register:
            clean_args = [a for a in args if a != "--register"]
            target_path = clean_args[0] if clean_args else path
            node = self.kernel.fs_service.vfs.get_node(target_path, cwd=self.kernel.get_cwd())
            if node is None:
                return CommandResult(success=False, error=f"Caminho não encontrado: '{target_path}'.")
            from os_simulator.filesystem.node import DirectoryNode
            if isinstance(node, DirectoryNode):
                recs = self.kernel.integrity_checker.register_tree_baseline(
                    self.kernel.fs_service, target_path, self.kernel.catalog
                )
                return CommandResult(
                    success=True,
                    output=f"Linha de base de integridade registrada para {len(recs)} arquivos em '{target_path}'.",
                )
            else:
                rec = self.kernel.integrity_checker.register_file_baseline(
                    self.kernel.fs_service, target_path, self.kernel.catalog
                )
                return CommandResult(
                    success=True,
                    output=f"Linha de base de integridade registrada para '{target_path}' (SHA-256: {rec.expected_sha256[:16]}...).",
                )

        report = self.kernel.antivirus_scanner.scan_path(path, context=self.kernel.context)
        return CommandResult(success=True, output=report.format_report(), data={"report": report})

    def cmd_security_status(self, args: List[str]) -> CommandResult:
        ctx = self.kernel.context
        mode_str = "MODO_KERNEL (Anel 0)" if ctx.is_kernel_mode() else "MODO_USUARIO (Anel 3)"
        total_users = len(self.kernel.user_manager.list_users())
        total_groups = len(self.kernel.user_manager.list_groups())
        total_events = len(self.kernel.audit_log.get_events(limit=10000))
        catalog_count = len(self.kernel.catalog.records) if hasattr(self.kernel, "catalog") else 0
        lines = [
            "======================================================================",
            "                   STATUS DO SISTEMA DE SEGURANÇA",
            "======================================================================",
            f"Usuário Ativo            : {ctx.username} (UID: {ctx.user_id})",
            f"Grupo Primário           : {ctx.primary_group}",
            f"Grupos da Sessão         : {', '.join(ctx.groups)}",
            f"Anel de Privilégio       : {mode_str}",
            f"Diretório de Trabalho    : {ctx.cwd}",
            "----------------------------------------------------------------------",
            "Mecanismo de Autenticação: PBKDF2-HMAC-SHA256 (600.000 iterações, salt 16B)",
            "Cifra de Armazenamento   : AES-256-GCM (Nonce 12B, Tag 16B)",
            f"Total de Usuários        : {total_users}",
            f"Total de Grupos          : {total_groups}",
            f"Registros no Baseline    : {catalog_count} arquivos monitorados",
            f"Eventos de Auditoria     : {total_events} registrados",
            "======================================================================",
        ]
        return CommandResult(success=True, output="\n".join(lines))

    def cmd_audit_log(self, args: List[str]) -> CommandResult:
        limit = 50
        user_filter = None
        type_filter = None
        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag == "--limit" and idx + 1 < len(args):
                limit = int(args[idx + 1])
                idx += 2
            elif flag.startswith("--limit="):
                limit = int(flag.split("=", 1)[1])
                idx += 1
            elif flag == "--user" and idx + 1 < len(args):
                user_filter = args[idx + 1]
                idx += 2
            elif flag.startswith("--user="):
                user_filter = flag.split("=", 1)[1]
                idx += 1
            elif flag == "--type" and idx + 1 < len(args):
                type_filter = args[idx + 1].upper()
                idx += 2
            elif flag.startswith("--type="):
                type_filter = flag.split("=", 1)[1].upper()
                idx += 1
            else:
                idx += 1

        events = self.kernel.audit_log.get_events(
            limit=limit,
            username=user_filter,
            event_type=type_filter,
        )
        output = self.kernel.audit_log.format_events(limit=limit)
        return CommandResult(success=True, output=output, data={"events": events})

    # =========================================================================
    # PROCESS AND MEMORY SUBSYSTEM HANDLERS (ETAPA 4)
    # =========================================================================

    def cmd_create_process(self, args: List[str]) -> CommandResult:
        """Create a new process with contiguous/paged memory and optional Stage 5 execution parameters."""
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: create_process --name \"<nome>\" --size <tamanho> --type <critical|normal>",
            )

        try:
            values, flags, positionals = parse_cli_args(
                args,
                value_flags={
                    "--name",
                    "--size",
                    "--type",
                    "--priority",
                    "--burst",
                    "--arrival",
                    "--io-profile",
                    "--io-every",
                    "--io-duration",
                    "--seed",
                    "--pages",
                },
                bool_flags={"--reserved", "--no-admit"},
                aliases={"-n": "--name", "-s": "--size", "-t": "--type", "-r": "--reserved"},
            )
        except ValueError as e:
            return CommandResult(success=False, error=str(e))

        name = values.get("--name") or (positionals[0] if len(positionals) > 0 else None)
        size_str = values.get("--size") or (positionals[1] if len(positionals) > 1 else None)

        if "--reserved" in flags:
            type_str = "critical"
        elif "--type" in values:
            type_str = values["--type"].lower()
        elif len(positionals) > 2 and positionals[2].lower() in ("critical", "normal"):
            type_str = positionals[2].lower()
        else:
            type_str = "normal"

        if not name or not size_str:
            return CommandResult(
                success=False,
                error="Parâmetros obrigatórios ausentes: --name e --size são necessários.",
            )

        if type_str not in ("critical", "normal"):
            return CommandResult(
                success=False,
                error=f"Tipo de processo inválido: '{type_str}'. Opções válidas: critical, normal.",
            )

        proc_type = ProcessType.CRITICAL if type_str == "critical" else ProcessType.NORMAL
        if proc_type == ProcessType.CRITICAL and not self.kernel.context.is_root():
            return CommandResult(
                success=False,
                error="Acesso negado: apenas o usuário root / Modo Kernel pode criar processos críticos na Área Reservada.",
            )

        try:
            size_bytes = parse_size_string(size_str)
        except ValueError as e:
            return CommandResult(success=False, error=str(e))

        stage5_keys = (
            "--priority",
            "--burst",
            "--arrival",
            "--io-profile",
            "--io-every",
            "--io-duration",
            "--seed",
            "--pages",
        )
        has_stage5_flags = any(k in values for k in stage5_keys) or ("--no-admit" in flags)

        io_profile_obj = None
        pages_pattern = None
        if not has_stage5_flags:
            proc = self.kernel.process_manager.create_process(
                name=name,
                size_bytes=size_bytes,
                process_type=proc_type,
                owner=self.kernel.context.username,
                arrival_time_ms=self.kernel.clock.now_ms,
            )

            try:
                self.kernel.memory_manager.allocate_process_memory(proc)
            except Exception as e:
                proc.terminate()
                if proc.name in self.kernel.process_manager.name_to_pid:
                    del self.kernel.process_manager.name_to_pid[proc.name]
                if proc.pid in self.kernel.process_manager.processes:
                    del self.kernel.process_manager.processes[proc.pid]
                return CommandResult(success=False, error=str(e))
        else:
            try:
                priority = (
                    parse_int_arg(values["--priority"], "Prioridade", min_val=1)
                    if "--priority" in values
                    else 3
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
                pages_pattern = (
                    parse_pages_pattern(values["--pages"])
                    if "--pages" in values
                    else None
                )
                io_profile_obj = build_io_profile(
                    io_profile_str=values.get("--io-profile"),
                    io_every=io_every,
                    io_duration=io_duration,
                    seed_val=seed_val,
                    default_seed=self.kernel.execution_engine.default_seed,
                )
                proc = self.kernel.execution_engine.submit_process(
                    name=name,
                    size_bytes=size_bytes,
                    process_type=proc_type,
                    owner=self.kernel.context.username,
                    priority=priority,
                    cpu_burst_ms=burst,
                    arrival_time_ms=arrival,
                    io_profile=io_profile_obj,
                    memory_access_pattern=pages_pattern,
                    admit_immediately="--no-admit" not in flags,
                )
            except (OSSimulatorException, ValueError) as e:
                return CommandResult(success=False, error=str(e))

        if proc_type == ProcessType.CRITICAL:
            seg = self.kernel.memory_manager.reserved_memory.get_segment_for_process(proc.name)
            ram_range = f"[{seg.start_address:04d} - {seg.end_address:04d} KB]" if seg else "N/A"
            lines = [
                f"[create_process] Processo crítico criado com sucesso.",
                f"PID            : {proc.pid}",
                f"Nome           : {proc.name}",
                f"Tipo           : CRITICAL (Área Reservada Contígua)",
                f"Tamanho        : {proc.size_kb} KB ({proc.size_bytes} bytes)",
                f"Intervalo RAM  : {ram_range}",
                f"Estado         : {proc.state.value}",
            ]
        else:
            pt = proc.page_table
            lines = [
                f"[create_process] Processo comum criado com sucesso.",
                f"PID            : {proc.pid}",
                f"Nome           : {proc.name}",
                f"Tipo           : NORMAL (Memória Virtual Paginada)",
                f"Tamanho        : {proc.size_kb} KB ({proc.size_bytes} bytes)",
                f"Páginas Lógicas: {pt.total_pages} páginas ({self.kernel.memory_manager.page_size} bytes cada)",
                f"Frag. Interna  : {pt.internal_fragmentation} bytes",
                f"Estado         : {proc.state.value}",
            ]

        if has_stage5_flags:
            lines.extend([
                f"Prioridade     : {proc.priority}",
                f"Burst de CPU   : {proc.cpu_burst_ms} ms",
                f"Chegada        : {proc.arrival_time_ms} ms",
                f"Perfil de E/S  : {describe_io_profile(io_profile_obj)}",
            ])
            if pages_pattern is not None:
                pages_desc = ", ".join(f"{p}{':W' if w else ''}" for p, w in pages_pattern)
                lines.append(f"Padrão Páginas : [{pages_desc}]")

        if hasattr(self.kernel, "audit_log") and self.kernel.audit_log:
            self.kernel.audit_log.log_event(
                event_type=AuditEventType.USER_MANAGEMENT,
                username=self.kernel.context.username,
                action="CREATE_PROCESS",
                result="SUCCESS",
                details={"pid": proc.pid, "name": proc.name, "type": proc.process_type.value},
            )

        return CommandResult(success=True, output="\n".join(lines), data={"process": proc.to_dict()})

    def cmd_terminate_process(self, args: List[str]) -> CommandResult:
        """Terminate a process and release its scheduler, mutex, event, and memory allocations."""
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: terminate_process --name \"<nome>\" ou terminate_process --pid <PID>",
            )

        try:
            values, _, positionals = parse_cli_args(
                args,
                value_flags={"--name", "--pid"},
                aliases={"-n": "--name", "-p": "--pid"},
            )
            identifier = (
                values.get("--name")
                or values.get("--pid")
                or (positionals[0] if positionals else None)
            )
        except ValueError as e:
            return CommandResult(success=False, error=str(e))

        if not identifier:
            return CommandResult(success=False, error="Nome ou PID do processo não especificado.")

        target_proc = self.kernel.process_manager.get_process(identifier)

        # Authorization check: critical processes require root/kernel mode
        if target_proc.is_critical and not self.kernel.context.is_root():
            return CommandResult(
                success=False,
                error="Acesso negado: apenas o usuário root / Modo Kernel pode encerrar processos críticos.",
            )

        # Authorization check: only owner or root can terminate process
        if target_proc.owner != self.kernel.context.username and not self.kernel.context.is_root():
            return CommandResult(
                success=False,
                error=f"Acesso negado: processo '{target_proc.name}' pertence ao usuário '{target_proc.owner}'.",
            )

        proc = self.kernel.execution_engine.terminate_process(identifier)

        lines = [
            f"[terminate_process] Processo encerrado com sucesso.",
            f"PID     : {proc.pid}",
            f"Nome    : {proc.name}",
            f"Tipo    : {proc.process_type.value}",
            f"Memória : Recursos liberados e devolvidos ao sistema.",
            f"Estado  : TERMINATED",
        ]
        return CommandResult(success=True, output="\n".join(lines), data={"process": proc.to_dict()})

    def cmd_memory_status(self, args: List[str]) -> CommandResult:
        """Display memory diagnostics for reserved, dynamic, and swap subsystems."""
        reserved_only = "--reserved" in args or "-r" in args
        status = self.kernel.memory_manager.get_status(reserved_only=reserved_only)
        res = status["reserved"]

        lines = [
            "======================================================================",
            "              DIAGNÓSTICO DA ÁREA DE MEMÓRIA RESERVADA",
            "======================================================================",
            f"Capacidade Total Reservada  : {_fmt_kb(res['total_capacity_kb'])} KB ({res['total_capacity_kb'] // 1024} MB)",
            "Segmentos Atuais:",
        ]
        for seg in res["segments"]:
            name = seg["process_name"] or "[BURACO LIVRE]"
            status_tag = "OCUPADO" if seg["status"] == "ALLOCATED" else "LIVRE"
            lines.append(
                f"  [{seg['start_address']:04d} - {seg['end_address']:04d} KB] : {name} ({_fmt_kb(seg['size_kb'])} KB) - {status_tag}"
            )
        lines.extend([
            "----------------------------------------------------------------------",
            f"Espaço Livre Total          : {_fmt_kb(res['free_kb'])} KB",
            f"Maior Bloco Livre Contíguo  : {_fmt_kb(res['max_contiguous_free_kb'])} KB",
            f"Fragmentação Externa        : {_fmt_kb(res['external_fragmentation_kb'])} KB",
            "======================================================================",
        ])

        if not reserved_only:
            dyn = status["dynamic"]
            swap = status["swap"]
            stats = status["statistics"]
            lines.extend([
                "",
                "======================================================================",
                "               DIAGNÓSTICO DA ÁREA DE MEMÓRIA DINÂMICA",
                "======================================================================",
                f"Total de Molduras Físicas   : {dyn['total_frames']} molduras ({_fmt_kb(dyn['total_frames'] * dyn['page_size'] // 1024)} KB)",
                f"Molduras Ocupadas           : {dyn['occupied_frames']} ({dyn['occupancy_percent']:.1f}%)",
                f"Molduras Livres             : {dyn['free_frames']}",
                f"Tamanho da Página/Moldura   : {_fmt_kb(dyn['page_size'])} bytes",
                f"Algoritmo de Substituição   : {dyn['replacement_algorithm']}",
                f"Total de Faltas de Página   : {stats['page_faults_total']} (Zero-Fill: {stats['page_faults_zero_fill']}, Imagem: {stats['page_faults_process_image']}, Swap: {stats['page_faults_swap']})",
                "----------------------------------------------------------------------",
                f"Slots Totais de Swap        : {swap['total_slots']} slots ({_fmt_kb(swap['total_slots'] * swap['slot_size'] // 1024)} KB)",
                f"Slots de Swap em Uso        : {swap['used_slots']}",
                f"Slots de Swap Livres        : {swap['free_slots']}",
                f"Operações de Swap (Out/In)  : {stats['swap_outs_total']} / {stats['swap_ins_total']}",
                f"Evicções (Limpa / Modificada): {stats['evictions_clean']} descartadas / {stats['evictions_dirty']} salvas no swap",
                "======================================================================",
            ])

        return CommandResult(success=True, output="\n".join(lines), data=status)

    def cmd_memory_compact(self, args: List[str]) -> CommandResult:
        """Perform sliding compaction on the reserved memory area."""
        if not self.kernel.context.is_root():
            return CommandResult(
                success=False,
                error="Acesso negado: a compactação de memória requer privilégios de root / Modo Kernel.",
            )

        moved, consolidated_free = self.kernel.memory_manager.compact_reserved()
        segments = self.kernel.memory_manager.reserved_memory.get_segments()

        lines = [
            "======================================================================",
            "        ÁREA DE MEMÓRIA RESERVADA APÓS COMPACTAÇÃO DESLIZANTE",
            "======================================================================",
            "Segmentos Reorganizados:",
        ]
        for seg in segments:
            name = seg.process_name or "[BLOCO LIVRE CONSOLIDADO]"
            status_tag = "OCUPADO" if seg.is_allocated else "LIVRE"
            lines.append(
                f"  [{seg.start_address:04d} - {seg.end_address:04d} KB] : {name} ({_fmt_kb(seg.size)} KB) - {status_tag}"
            )
        lines.extend([
            "----------------------------------------------------------------------",
            f"Fragmentação Externa        : 0 KB (Capacidade máxima contígua: {_fmt_kb(consolidated_free)} KB)",
            "======================================================================",
        ])
        return CommandResult(success=True, output="\n".join(lines), data={"moved": moved, "free_kb": consolidated_free})


    def cmd_translate_address(self, args: List[str]) -> CommandResult:
        """Translate logical page or byte address to physical frame/address."""
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: translate_address --process \"<nome>\" --page <numero_pagina> ou translate_address --pid <PID> --address <endereco>",
            )

        process_id = None
        page = None
        address = None

        idx = 0
        positionals = []
        while idx < len(args):
            flag = args[idx]
            if flag in ("--process", "-p") and idx + 1 < len(args):
                process_id = args[idx + 1]
                idx += 2
            elif flag.startswith("--process="):
                process_id = flag.split("=", 1)[1]
                idx += 1
            elif flag == "--pid" and idx + 1 < len(args):
                process_id = args[idx + 1]
                idx += 2
            elif flag.startswith("--pid="):
                process_id = flag.split("=", 1)[1]
                idx += 1
            elif flag == "--page" and idx + 1 < len(args):
                page = int(args[idx + 1])
                idx += 2
            elif flag.startswith("--page="):
                page = int(flag.split("=", 1)[1])
                idx += 1
            elif flag == "--address" and idx + 1 < len(args):
                address = int(args[idx + 1])
                idx += 2
            elif flag.startswith("--address="):
                address = int(flag.split("=", 1)[1])
                idx += 1
            else:
                positionals.append(flag)
                idx += 1

        if process_id is None and len(positionals) > 0:
            process_id = positionals[0]
        if page is None and address is None and len(positionals) > 1:
            try:
                num = int(positionals[1])
                if num >= 4096:
                    address = num
                else:
                    page = num
            except ValueError:
                pass

        if process_id is None or (page is None and address is None):
            return CommandResult(
                success=False,
                error="Parâmetros insuficientes: informe --process/--pid e --page ou --address.",
            )

        proc = self.kernel.process_manager.get_process(process_id)

        if address is not None:
            try:
                res = self.kernel.memory_manager.translate_address(proc, address)
                lines = [
                    "[TRADUÇÃO DE ENDEREÇO LÓGICO COMPLETO]",
                    f"Processo         : {proc.name} (PID {proc.pid})",
                    f"Endereço Lógico  : {res['logical_address']}",
                    f"Página Lógica (p): {res['logical_page']}",
                    f"Deslocamento (d) : {res['offset']}",
                    f"Moldura Física (f): {res['frame_id']}",
                    f"Endereço Físico  : {res['physical_address']}",
                ]
                return CommandResult(success=True, output="\n".join(lines), data=res)
            except PageFaultException as e:
                return CommandResult(
                    success=True,
                    output=(
                        f"[FALTA DE PÁGINA DETECTADA (PAGE FAULT)]\n"
                        f"Processo         : {proc.name} (PID {proc.pid})\n"
                        f"Endereço Lógico  : {address}\n"
                        f"Página Lógica (p): {address // self.kernel.memory_manager.page_size}\n"
                        f"Estado na RAM    : AUSENTE (Origem: {e.page_origin})\n"
                        f"Ação do SO       : Requer execução de instrução (execute_step) para carga."
                    ),
                    data={"page_fault": True, "pid": proc.pid, "logical_page": e.logical_page},
                )
        else:
            try:
                res = self.kernel.memory_manager.translate_page(proc, page)
                lines = [
                    "[TRADUÇÃO DE ENDEREÇO VIRTUAL]",
                    f"Processo            : {proc.name} (PID {proc.pid})",
                    f"Página Lógica       : {res['logical_page']}",
                    f"Moldura Física      : {res['frame_id']}",
                    f"Endereço Base Físico: {res['base_address']}",
                    f"Intervalo Físico    : [{res['base_address']} - {res['end_address']} bytes]",
                    f"Estado na RAM       : PRESENTE",
                ]
                return CommandResult(success=True, output="\n".join(lines), data=res)
            except PageFaultException as e:
                return CommandResult(
                    success=True,
                    output=(
                        f"[FALTA DE PÁGINA (PAGE FAULT)]\n"
                        f"Processo      : {proc.name} (PID {proc.pid})\n"
                        f"Página Lógica : {page}\n"
                        f"Estado na RAM : AUSENTE (Página não carregada em moldura física)\n"
                        f"Origem Válida : {e.page_origin}\n"
                        f"Ação do SO    : Será carregada sob demanda quando acessada por execute_step."
                    ),
                    data={"page_fault": True, "pid": proc.pid, "logical_page": page, "origin": e.page_origin},
                )

    def cmd_execute_step(self, args: List[str]) -> CommandResult:
        """Simulate CPU instruction execution and memory access."""
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: execute_step --process \"<nome>\" --instruction \"<instrucao>\"",
            )

        process_id = None
        instruction = None

        idx = 0
        positionals = []
        while idx < len(args):
            flag = args[idx]
            if flag in ("--process", "-p") and idx + 1 < len(args):
                process_id = args[idx + 1]
                idx += 2
            elif flag.startswith("--process="):
                process_id = flag.split("=", 1)[1]
                idx += 1
            elif flag == "--pid" and idx + 1 < len(args):
                process_id = args[idx + 1]
                idx += 2
            elif flag.startswith("--pid="):
                process_id = flag.split("=", 1)[1]
                idx += 1
            elif flag in ("--instruction", "-i") and idx + 1 < len(args):
                instruction = args[idx + 1]
                idx += 2
            elif flag.startswith("--instruction="):
                instruction = flag.split("=", 1)[1]
                idx += 1
            else:
                positionals.append(flag)
                idx += 1

        if process_id is None and len(positionals) > 0:
            process_id = positionals[0]
        if instruction is None and len(positionals) > 1:
            instruction = " ".join(positionals[1:])

        if not process_id or not instruction:
            return CommandResult(
                success=False,
                error="Parâmetros insuficientes: --process e --instruction são obrigatórios.",
            )

        proc = self.kernel.process_manager.get_process(process_id)
        res = self.kernel.memory_manager.execute_instruction(proc, instruction)

        lines = [
            "[EXECUÇÃO DE INSTRUÇÃO E ACESSO À MEMÓRIA]",
            f"Processo       : {proc.name} (PID {proc.pid})",
            f"Instrução      : {instruction}",
            f"Tipo de Acesso : {'ESCRITA (dirty=True)' if res['is_write'] else 'LEITURA'}",
            f"Página Alvo    : Página {res['logical_page']} -> Moldura {res['frame_id']}",
            f"Falta de Página: {'SIM (Tratada e resolvida)' if res['page_fault'] else 'NÃO (Página já residente)'}",
        ]
        if res["page_fault"] and res["fault_details"]:
            fd = res["fault_details"]
            lines.append(f"  Origem Válida: {fd['page_origin']}")
            if fd["victim"]:
                v = fd["victim"]
                action_desc = f"{v['action']} (dirty={v['dirty']})"
                if v.get("swap_slot_id") is not None:
                    action_desc += f" -> Gravada no Swap Slot {v['swap_slot_id']}"
                lines.append(f"  Vítima Eleita: PID {v['pid']}, Página {v['logical_page']} (Moldura {v['frame_id']}) -> {action_desc}")
            else:
                lines.append("  Alocação     : Moldura livre disponível sem necessidade de substituição.")

        return CommandResult(success=True, output="\n".join(lines), data=res)

    def cmd_page_replacement(self, args: List[str]) -> CommandResult:
        """Query or switch active page replacement policy."""
        if not args:
            return CommandResult(
                success=True,
                output=f"Algoritmo de substituição de páginas ativo: {self.kernel.memory_manager.algorithm.value}",
            )

        algo = None
        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag in ("--algorithm", "--set", "-a") and idx + 1 < len(args):
                algo = args[idx + 1]
                idx += 2
            elif flag.startswith("--algorithm="):
                algo = flag.split("=", 1)[1]
                idx += 1
            else:
                algo = flag
                idx += 1

        try:
            self.kernel.memory_manager.set_replacement_policy(algo)
            return CommandResult(
                success=True,
                output=f"Algoritmo de substituição de páginas alterado para: {self.kernel.memory_manager.algorithm.value}",
            )
        except ValueError as e:
            return CommandResult(success=False, error=str(e))

    def cmd_page_table(self, args: List[str]) -> CommandResult:
        """Display page table entries and internal fragmentation for a process."""
        if not args:
            return CommandResult(
                success=False,
                error="Sintaxe: page_table --process \"<nome>\" ou page_table --pid <PID>",
            )

        identifier = None
        idx = 0
        while idx < len(args):
            flag = args[idx]
            if flag in ("--process", "-p") and idx + 1 < len(args):
                identifier = args[idx + 1]
                idx += 2
            elif flag.startswith("--process="):
                identifier = flag.split("=", 1)[1]
                idx += 1
            elif flag in ("--pid", "-pid") and idx + 1 < len(args):
                identifier = args[idx + 1]
                idx += 2
            elif flag.startswith("--pid="):
                identifier = flag.split("=", 1)[1]
                idx += 1
            else:
                identifier = flag
                idx += 1

        proc = self.kernel.process_manager.get_process(identifier)
        if not proc.page_table:
            return CommandResult(
                success=False,
                error=f"Processo '{proc.name}' é do tipo {proc.process_type.value} e não utiliza tabela de páginas.",
            )

        pt = proc.page_table
        lines = [
            "======================================================================",
            f"      TABELA DE PÁGINAS — PROCESSO '{proc.name}' (PID {proc.pid})",
            "======================================================================",
            f"{'Página':<8} | {'Moldura':<8} | {'Presente':<9} | {'Modificada':<11} | {'Referenciada':<13} | {'Origem':<20} | {'Swap Slot':<9}",
            "-" * 88,
        ]
        for p_idx in sorted(pt.entries.keys()):
            e = pt.entries[p_idx]
            frame_str = str(e.frame_id) if e.frame_id is not None else "-"
            swap_str = str(e.swap_slot_id) if e.swap_slot_id is not None else "-"
            lines.append(
                f"{e.logical_page:<8} | {frame_str:<8} | {str(e.present):<9} | {str(e.dirty):<11} | {str(e.referenced):<13} | {e.page_origin.value:<20} | {swap_str:<9}"
            )
        lines.extend([
            "-" * 88,
            f"Total de Páginas     : {pt.total_pages} páginas ({pt.total_pages * pt.page_size} bytes virtuais)",
            f"Tamanho do Processo  : {proc.size_bytes} bytes ({proc.size_kb} KB)",
            f"Fragmentação Interna : {pt.internal_fragmentation} bytes (na última página)",
            "======================================================================",
        ])
        return CommandResult(success=True, output="\n".join(lines), data=pt.to_dict())

    def cmd_memory_map(self, args: List[str]) -> CommandResult:
        """Display visual unified physical and virtual memory map."""
        res_segs = self.kernel.memory_manager.reserved_memory.get_segments()
        dyn_frames = self.kernel.memory_manager.physical_memory.frames

        lines = [
            "======================================================================",
            "                   MAPA GERAL DA MEMÓRIA FÍSICA SIMULADA",
            "======================================================================",
            "[ÁREA RESERVADA CONTÍGUA - 0 a 4095 KB]",
        ]
        for seg in res_segs:
            pname = seg.process_name or "[LIVRE]"
            lines.append(f"  [{seg.start_address:04d} - {seg.end_address:04d} KB] : {pname:<22} ({seg.size:>4} KB) [{seg.status.value}]")

        lines.extend([
            "",
            "[ÁREA DINÂMICA PAGINADA - MOLDURAS FÍSICAS]",
        ])
        for frame in dyn_frames:
            if frame.occupied:
                desc = f"PID {frame.owner_pid} (Página {frame.logical_page})"
                status_str = "OCUPADA"
            else:
                desc = "[LIVRE]"
                status_str = "LIVRE"
            lines.append(f"  Moldura {frame.frame_id:02d} [{frame.frame_id * 4096:06d} - {(frame.frame_id + 1) * 4096 - 1:06d} B] : {desc:<25} [{status_str}]")

        lines.append("======================================================================")
        return CommandResult(success=True, output="\n".join(lines))


    def cmd_help(self, args: List[str]) -> CommandResult:
        lines = [
            "======================================================================",
            "                 COMANDOS DISPONÍVEIS — OS SIMULATOR",
            "======================================================================",
            "SISTEMA DE ARQUIVOS (ETAPA 1):",
            "  mkdir <caminho>                   : Cria um diretório no VFS",
            "  create <caminho> [--size <tam>]   : Cria arquivo com tamanho opcional",
            "  write_file <caminho> \"<texto>\"   : Grava dados no arquivo",
            "  read_file <caminho>               : Lê o conteúdo do arquivo",
            "  delete_file <caminho>             : Exclui um arquivo e libera blocos",
            "  delete_directory <caminho>        : Exclui um diretório vazio",
            "  fs_status [--details]             : Exibe diagnóstico e fragmentação",
            "  ls [<caminho>]                    : Lista conteúdo de diretório",
            "  cd <caminho>                      : Altera o diretório de trabalho",
            "  pwd                               : Exibe o diretório de trabalho atual",
            "  tree                              : Exibe a árvore visual do sistema",
            "",
            "GERENCIAMENTO DE E/S E ESCALONAMENTO (ETAPA 2):",
            "  io_status                         : Exibe diagnóstico do subsistema de E/S",
            "  io_scheduler [--set <alg>]        : Consulta ou altera escalonador (fcfs, sstf, scan, cscan)",
            "  io_benchmark [--algorithm <alg>]  : Simula escalonamento e compara algoritmos",
            "",
            "DISCO DE ESTADO SÓLIDO (SSD) E WEAR LEVELING (ETAPA 2):",
            "  ssd_status [--mode <modo>]        : Exibe status da FTL, ciclos e Wear Leveling",
            "",
            "ARRANJOS RAID (ETAPA 2):",
            "  raid_status                       : Exibe status de saúde e membros do arranjo RAID",
            "  raid_fail --disk <id>             : Simula falha física de um disco no arranjo",
            "  raid_rebuild --disk <id>          : Reconstrói dados do disco falho via redundância",
            "  raid_init --level <0|1|4|5>       : Inicializa novo arranjo RAID na simulação",
            "",
            "SEGURANÇA E PROTEÇÃO (ETAPA 3):",
            "  login --user <nome> [--password]  : Inicia sessão com verificação PBKDF2",
            "  logout                            : Encerra a sessão ativa",
            "  whoami                            : Exibe usuário ativo, grupos e anel de privilégio",
            "  groups [<usuario>]                : Exibe os grupos aos quais o usuário pertence",
            "  useradd <nome> [--group <g>]      : Cria novo usuário no sistema",
            "  userdel <nome>                    : Remove usuário existente",
            "  usermod <nome> [--group <g>]      : Modifica atributos de usuário e grupos",
            "  groupadd <nome>                   : Cria novo grupo no sistema",
            "  groupdel <nome>                   : Remove grupo existente",
            "  chmod <modo> <caminho>            : Altera permissões rwx (ex.: 750, 644)",
            "  chown <dono>[:<grupo>] <caminho>  : Transfere propriedade de arquivo/diretório",
            "  chgrp <grupo> <caminho>           : Altera o grupo proprietário de arquivo/diretório",
            "  security_status                   : Exibe resumo e métricas do sistema de segurança",
            "  encrypt_file <caminho> [--key <k>]: Criptografa arquivo com AES-256-GCM",
            "  decrypt_file <caminho> [--key <k>]: Descriptografa arquivo e valida tag AEAD",
            "  antivirus_scan [<caminho>]        : Executa varredura de integridade e assinaturas",
            "  integrity_check [<caminho>]       : Valida ou registra linha de base de integridade",
            "  audit_log [--limit <n>]           : Exibe a trilha de auditoria do sistema",
            "",
            "GERENCIAMENTO DE MEMÓRIA E PROCESSOS (ETAPA 4):",
            "  create_process --name <n> --size <s> --type <t>: Cria processo com alocação contígua ou paginada",
            "  terminate_process --name <n>                   : Encerra processo e libera recursos de memória",
            "  memory_status [--reserved]                     : Exibe mapa de memória, fragmentação e molduras",
            "  memory_compact [--reserved]                    : Executa compactação deslizante da área reservada",
            "  translate_address --process <p> --page <n>     : Traduz página lógica para moldura física (MMU)",
            "  execute_step --process <p> --instruction <i>   : Simula acesso de instrução à memória e Page Fault",
            "  page_replacement --algorithm <alg>             : Seleciona algoritmo de reposição (lru, second_chance)",
            "  page_table --process <p>                       : Exibe a tabela de páginas do processo",
            "  memory_map                                     : Exibe o mapa unificado de memória física e virtual",
            "",
            "PROCESSOS, THREADS, ESCALONAMENTO E CONCORRÊNCIA (ETAPA 5):",
            "  create_process ... [--priority <p>] [--burst <ms>] [--arrival <ms>] [--io-profile <perf>] [--no-admit]",
            "  ps / process_status [--all]                    : Lista processos, threads, estados e bloqueios",
            "  process_admit --process <p>                    : Admite processo em NEW para READY",
            "  thread_create --process <p> --name <t> [...]   : Cria thread escalonável em processo existente",
            "  thread_status [--process <p>]                  : Exibe status detalhado das threads simuladas",
            "  sched_config [--algorithm <alg>] [--quantum <ms>] [--seed <n>]: Configura ou exibe escalonador",
            "  sched_status                                   : Exibe thread RUNNING, filas por prioridade e bloqueios",
            "  sched_step [--ms <n>]                          : Avança simulação por N milissegundos lógicos",
            "  sched_run [--max-ms <n>] [--until-process <p>] [--until-event <ev>]: Executa simulação completa",
            "  process_syscall --process <p> --type <t> [...] : Agenda ou executa syscall imediata (--now)",
            "  mutex_create [--name] <nome>                   : Cria mutex para sincronização de threads",
            "  mutex_lock --mutex <m> --process <p> [--thread <t>]: Tenta adquirir mutex (com fila FIFO)",
            "  mutex_unlock --mutex <m> --process <p> [--thread <t>]: Libera mutex e realiza handoff FIFO",
            "  mutex_status                                   : Exibe estado dos mutexes, donos e filas de espera",
            "  mutex_demo [--scenario buffer_video] [--quantum <ms>]: Executa cenário Buffer_Video",
            "  deadlock_check                                 : Verifica ciclos Wait-For e estagnação",
            "  memory_frames                                  : Exibe resumo ao vivo das molduras físicas (frames)",
            "  sim_metrics                                    : Exibe métricas de execução (WT, TAT, CPU, faults)",
            "  sim_timeline [--limit <n>] [--gantt]           : Exibe linha do tempo e/ou diagrama de Gantt",
            "  sim_reset                                      : Reinicia relógio, filas, mutexes e métricas",
            "",
            "SISTEMA:",
            "  help                              : Exibe esta lista de ajuda",
            "  exit                              : Encerra a sessão do simulador",
            "======================================================================",
        ]
        return CommandResult(success=True, output="\n".join(lines))
