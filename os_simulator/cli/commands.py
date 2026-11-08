"""CLI command handlers and argument parser for OS Simulator."""

import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from os_simulator.core.exceptions import OSSimulatorException
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import AllocationStrategy


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


class CommandDispatcher:
    """Dispatches CLI commands to the appropriate kernel handlers."""

    def __init__(self, kernel: SimulationKernel):
        self.kernel = kernel

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
        node = self.kernel.fs_service.mkdir(path, cwd=self.kernel.get_cwd())
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
            path, size_bytes=size_bytes, strategy=strategy, cwd=self.kernel.get_cwd()
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
            path, content, append=append, cwd=self.kernel.get_cwd()
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
        content = self.kernel.fs_service.read_file(path, cwd=self.kernel.get_cwd())
        return CommandResult(success=True, output=content, data={"content": content})

    def cmd_delete_file(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: delete_file <caminho_arquivo>")
        path = args[0]
        self.kernel.fs_service.delete_file(path, cwd=self.kernel.get_cwd())
        return CommandResult(success=True, output=f"Arquivo excluído com sucesso: '{path}'.")

    def cmd_delete_directory(self, args: List[str]) -> CommandResult:
        if not args:
            return CommandResult(success=False, error="Sintaxe: delete_directory <caminho_diretorio>")
        path = args[0]
        self.kernel.fs_service.delete_directory(path, cwd=self.kernel.get_cwd())
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

    def cmd_help(self, args: List[str]) -> CommandResult:
        lines = [
            "======================================================================",
            "                 COMANDOS DISPONÍVEIS — OS SIMULATOR",
            "======================================================================",
            "mkdir <caminho>                   : Cria um diretório no VFS",
            "create <caminho> [--size <tam>]   : Cria arquivo com tamanho opcional",
            "write_file <caminho> \"<texto>\"   : Grava dados no arquivo",
            "read_file <caminho>               : Lê o conteúdo do arquivo",
            "delete_file <caminho>             : Exclui um arquivo e libera blocos",
            "delete_directory <caminho>        : Exclui um diretório vazio",
            "fs_status [--details]             : Exibe diagnóstico e fragmentação",
            "ls [<caminho>]                    : Lista conteúdo de diretório",
            "cd <caminho>                      : Altera o diretório de trabalho",
            "pwd                               : Exibe o diretório de trabalho atual",
            "tree                              : Exibe a árvore visual do sistema",
            "exit                              : Encerra a sessão do simulador",
            "======================================================================",
        ]
        return CommandResult(success=True, output="\n".join(lines))
