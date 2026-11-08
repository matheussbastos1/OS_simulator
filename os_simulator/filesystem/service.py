"""Filesystem Service orchestrating VFS, Inodes, and Block Device."""

import math
from typing import Any, Dict, List, Optional, Tuple

from os_simulator.core.exceptions import (
    FileNotFoundException,
    InodeTableExhaustedException,
    IsADirectoryException,
)
from os_simulator.core.ports import AuthorizationPort, BlockDevicePort, BootstrapSecurityPolicy
from os_simulator.core.types import AllocationStrategy, BlockStatus, NodeType
from os_simulator.filesystem.allocation import (
    AllocationStrategyBase,
    AllocationStrategyFactory,
    ContiguousAllocation,
)
from os_simulator.filesystem.inode import Inode
from os_simulator.filesystem.node import DirectoryNode, FileNode, Node
from os_simulator.filesystem.vfs import VirtualFileSystem


class FileSystemService:
    """Core filesystem service managing files, directories, i-nodes, and block allocation."""

    def __init__(
        self,
        block_device: BlockDevicePort,
        auth_port: Optional[AuthorizationPort] = None,
        max_inodes: int = 128,
        default_strategy: AllocationStrategy = AllocationStrategy.INDEXED,
    ):
        self.device = block_device
        self.auth = auth_port or BootstrapSecurityPolicy()
        self.max_inodes = max_inodes
        self.default_strategy = default_strategy

        # Root i-node is ID 1
        self.next_inode_id = 2
        self.inode_table: Dict[int, Inode] = {
            1: Inode(
                inode_id=1,
                node_type=NodeType.DIRECTORY,
                permissions="755",
                owner="root",
                group="root",
                allocation_strategy=default_strategy,
            )
        }

        self.vfs = VirtualFileSystem(root_inode_id=1)

    def _allocate_inode_id(self) -> int:
        """Find next available inode_id."""
        if len(self.inode_table) >= self.max_inodes:
            raise InodeTableExhaustedException("Tabela de i-nodes esgotada.")
        start_id = self.next_inode_id
        while self.next_inode_id in self.inode_table:
            self.next_inode_id += 1
            if self.next_inode_id > self.max_inodes:
                self.next_inode_id = 1
            if self.next_inode_id == start_id:
                raise InodeTableExhaustedException("Tabela de i-nodes esgotada.")
        allocated_id = self.next_inode_id
        self.next_inode_id += 1
        return allocated_id

    def mkdir(self, path: str, cwd: str = "/") -> DirectoryNode:
        """Create a new directory in the hierarchy."""
        inode_id = self._allocate_inode_id()
        dir_inode = Inode(
            inode_id=inode_id,
            node_type=NodeType.DIRECTORY,
            permissions="755",
            owner="root",
            group="root",
            allocation_strategy=self.default_strategy,
        )
        try:
            node = self.vfs.mkdir(path, inode_id=inode_id, cwd=cwd)
            self.inode_table[inode_id] = dir_inode
            return node
        except Exception:
            raise

    def create_file(
        self,
        path: str,
        size_bytes: int = 0,
        strategy: Optional[AllocationStrategy] = None,
        cwd: str = "/",
    ) -> FileNode:
        """Create a file, optionally pre-allocating size_bytes."""
        chosen_strategy = strategy or self.default_strategy
        inode_id = self._allocate_inode_id()

        file_inode = Inode(
            inode_id=inode_id,
            node_type=NodeType.FILE,
            file_size=0,
            permissions="644",
            owner="root",
            group="root",
            allocation_strategy=chosen_strategy,
        )

        try:
            node = self.vfs.create_file(path, inode_id=inode_id, cwd=cwd)
            self.inode_table[inode_id] = file_inode

            if size_bytes > 0:
                strategy_handler = AllocationStrategyFactory.get_strategy(chosen_strategy)
                strategy_handler.allocate(self.device, file_inode, size_bytes)
                # Write empty zero payload
                zero_data = b"\x00" * size_bytes
                strategy_handler.write_data(self.device, file_inode, zero_data)

            return node
        except Exception:
            self.inode_table.pop(inode_id, None)
            raise

    def write_file(
        self,
        path: str,
        content: str | bytes | bytearray,
        append: bool = False,
        cwd: str = "/",
    ) -> Dict[str, Any]:
        """Write content into file, allocating necessary blocks."""
        raw_data = content.encode("utf-8") if isinstance(content, str) else bytes(content)

        node = self.vfs.get_node(path, cwd)
        if node is None:
            # Create file implicitly if missing
            file_node = self.create_file(path, size_bytes=0, cwd=cwd)
        elif isinstance(node, FileNode):
            file_node = node
        else:
            raise IsADirectoryException(f"'{path}' é um diretório e não pode ser gravado como arquivo.")

        inode = self.inode_table[file_node.inode_id]
        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)

        if append and inode.file_size > 0:
            existing_data = strategy_handler.read_data(self.device, inode)
            raw_data = bytes(existing_data) + raw_data

        strategy_handler.write_data(self.device, inode, raw_data)

        # Collect write statistics for report
        internal_frag = inode.get_internal_fragmentation(self.device.get_block_size())
        data_blocks = list(inode.allocated_blocks)
        allocated_capacity = inode.get_allocated_data_bytes(self.device.get_block_size())

        return {
            "path": file_node.get_path(),
            "real_size": len(raw_data),
            "allocated_blocks": data_blocks,
            "index_block_id": inode.index_block_id,
            "allocated_capacity": allocated_capacity,
            "internal_fragmentation": internal_frag,
            "external_fragmentation": 0,  # 0 for this file's allocation
        }

    def read_file(self, path: str, cwd: str = "/") -> str:
        """Read and return string content of a file."""
        node = self.vfs.get_file(path, cwd)
        inode = self.inode_table[node.inode_id]
        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)
        data = strategy_handler.read_data(self.device, inode)
        return data.decode("utf-8", errors="replace")

    def read_file_bytes(self, path: str, cwd: str = "/") -> bytearray:
        """Read and return raw binary content of a file."""
        node = self.vfs.get_file(path, cwd)
        inode = self.inode_table[node.inode_id]
        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)
        return strategy_handler.read_data(self.device, inode)

    def delete_file(self, path: str, cwd: str = "/") -> None:
        """Delete file from tree and release its blocks and i-node."""
        node = self.vfs.get_file(path, cwd)
        inode = self.inode_table[node.inode_id]
        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)
        strategy_handler.free(self.device, inode)
        self.inode_table.pop(inode.inode_id, None)
        self.vfs.delete_file(path, cwd)

    def delete_directory(self, path: str, cwd: str = "/") -> None:
        """Delete an empty directory."""
        freed_inode_id = self.vfs.delete_directory(path, cwd)
        self.inode_table.pop(freed_inode_id, None)

    def get_fs_status(self, details: bool = False) -> Dict[str, Any]:
        """Compute full diagnostic report of filesystem and storage device."""
        block_size = self.device.get_block_size()
        total_blocks = self.device.get_capacity()
        free_blocks = self.device.get_free_count()

        # Count occupied blocks by category
        data_blocks_count = 0
        index_blocks_count = 0
        total_data_bytes = 0
        total_internal_frag = 0

        for inode in self.inode_table.values():
            if inode.node_type == NodeType.FILE:
                data_blocks_count += len(inode.allocated_blocks)
                if inode.index_block_id is not None:
                    index_blocks_count += 1
                total_data_bytes += inode.file_size
                total_internal_frag += inode.get_internal_fragmentation(block_size)

        occupied_blocks = data_blocks_count + index_blocks_count
        metadata_overhead = index_blocks_count * block_size

        # Find largest contiguous free block span
        contiguous_helper = ContiguousAllocation()
        spans = contiguous_helper._find_free_spans(self.device)
        max_contiguous_span = max((s[1] for s in spans), default=0)

        # External fragmentation is free space scattered outside largest contiguous chunk
        external_fragmentation_bytes = (free_blocks - max_contiguous_span) * block_size

        return {
            "strategy": self.default_strategy.value,
            "block_size": block_size,
            "total_blocks": total_blocks,
            "total_bytes": total_blocks * block_size,
            "occupied_blocks": occupied_blocks,
            "data_blocks_count": data_blocks_count,
            "index_blocks_count": index_blocks_count,
            "free_blocks": free_blocks,
            "total_inodes": self.max_inodes,
            "occupied_inodes": len(self.inode_table),
            "free_inodes": self.max_inodes - len(self.inode_table),
            "data_space_used": total_data_bytes,
            "metadata_overhead": metadata_overhead,
            "internal_fragmentation": total_internal_frag,
            "external_fragmentation": external_fragmentation_bytes,
            "max_contiguous_blocks": max_contiguous_span,
            "needs_compaction": external_fragmentation_bytes > 0,
            "details": details,
        }

    def format_fs_status(self, details: bool = False) -> str:
        """Render diagnostic report matching official academic format."""
        status = self.get_fs_status(details=details)
        strategy_label = {
            "INDEXED": "INDEXADA (i-node)",
            "CONTIGUOUS": "CONTÍGUA",
            "LINKED_FAT": "ENCADEADA (FAT)",
        }.get(status["strategy"], status["strategy"])

        lines = [
            "======================================================================",
            "                  DIAGNÓSTICO DO SISTEMA DE ARQUIVOS",
            "======================================================================",
            f"Estratégia de Alocação Ativa : {strategy_label}",
            f"Tamanho do Bloco             : {status['block_size']:,} bytes ({status['block_size'] // 1024} KB)".replace(",", "."),
            f"Total de Blocos no Disco     : {status['total_blocks']:,} blocos ({status['total_bytes'] // 1024:,} KB)".replace(",", "."),
            f"Blocos de Dados Ocupados     : {status['data_blocks_count']} blocos ({status['data_blocks_count'] * status['block_size']:,} bytes)".replace(",", "."),
            f"Blocos de Índice Ocupados    : {status['index_blocks_count']} blocos ({status['index_blocks_count'] * status['block_size']:,} bytes)".replace(",", "."),
            f"Blocos Livres                : {status['free_blocks']:,} blocos ({(status['free_blocks'] * status['block_size']):,} bytes)".replace(",", "."),
            f"Total de i-nodes             : {status['total_inodes']} (Ocupados: {status['occupied_inodes']} | Livres: {status['free_inodes']})",
            "----------------------------------------------------------------------",
            f"Espaço Ocupado pelos Dados   : {status['data_space_used']:,} bytes".replace(",", "."),
            f"Sobrecarga de Metadados      : {status['metadata_overhead']:,} bytes".replace(",", "."),
            f"Fragmentação Interna Total   : {status['internal_fragmentation']:,} bytes".replace(",", "."),
            f"Fragmentação Externa (Geral) : {status['external_fragmentation']:,} bytes (maior contíguo: {status['max_contiguous_blocks']} blocos)".replace(",", "."),
            "======================================================================",
        ]

        if details:
            lines.append("\n[MAPA DE OCUPAÇÃO DOS BLOCOS]")
            blocks_row: List[str] = []

            # Determine real allocation state from filesystem metadata
            index_blocks = {
                inode.index_block_id
                for inode in self.inode_table.values()
                if inode.index_block_id is not None
            }
            data_blocks = {
                b_id
                for inode in self.inode_table.values()
                for b_id in inode.allocated_blocks
            }

            for b_id in range(self.device.get_capacity()):
                if not self.device.is_available(b_id):
                    status_char = "X"
                elif b_id in index_blocks:
                    status_char = "I"
                elif b_id in data_blocks:
                    status_char = "D"
                elif self.device.is_block_free(b_id):
                    status_char = "."
                else:
                    status_char = "D"

                blocks_row.append(f"[{b_id:02d}:{status_char}]")
                if len(blocks_row) == 8:
                    lines.append(" ".join(blocks_row))
                    blocks_row = []
            if blocks_row:
                lines.append(" ".join(blocks_row))
            lines.append("Legenda: . = Livre, D = Dados, I = Índice, X = Danificado")

        return "\n".join(lines)

    def get_tree_string(self) -> str:
        """Return visual directory tree."""
        return self.vfs.root.format_tree(inode_table=self.inode_table)
