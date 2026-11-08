"""Hierarchical node structures for OS Simulator Virtual File System."""

from abc import ABC
import time
from typing import Dict, List, Optional

from os_simulator.core.exceptions import (
    DirectoryNotEmptyException,
    FileAlreadyExistsException,
    FileNotFoundException,
    IsADirectoryException,
    NotADirectoryException,
)
from os_simulator.core.types import NodeType


class Node(ABC):
    """Abstract base class representing a node in the VFS hierarchy."""

    def __init__(
        self,
        name: str,
        node_type: NodeType,
        inode_id: int,
        parent: Optional["DirectoryNode"] = None,
    ):
        if "/" in name and name != "/":
            raise ValueError(f"Nome de nó não pode conter barras: '{name}'")
        self.name = name
        self.node_type = node_type
        self.inode_id = inode_id
        self.parent = parent
        self.created_at = time.time()
        self.modified_at = self.created_at

    def get_path(self) -> str:
        """Calculate canonical absolute path of this node from root."""
        if self.parent is None:
            return "/" if self.name == "/" else f"/{self.name}"
        parent_path = self.parent.get_path()
        if parent_path == "/":
            return f"/{self.name}"
        return f"{parent_path}/{self.name}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' inode={self.inode_id} path='{self.get_path()}'>"


class FileNode(Node):
    """Represents a regular file in the filesystem tree."""

    def __init__(
        self,
        name: str,
        inode_id: int,
        parent: Optional["DirectoryNode"] = None,
    ):
        super().__init__(name, NodeType.FILE, inode_id, parent)


class DirectoryNode(Node):
    """Represents a directory containing child nodes."""

    def __init__(
        self,
        name: str,
        inode_id: int,
        parent: Optional["DirectoryNode"] = None,
    ):
        super().__init__(name, NodeType.DIRECTORY, inode_id, parent)
        self.children: Dict[str, Node] = {}

    def add_child(self, node: Node) -> None:
        """Add a child node to this directory."""
        if node.name in self.children:
            raise FileAlreadyExistsException(
                f"Elemento '{node.name}' já existe no diretório '{self.get_path()}'."
            )
        node.parent = self
        self.children[node.name] = node
        self.modified_at = time.time()

    def remove_child(self, name: str) -> Node:
        """Remove and return child node by name."""
        if name not in self.children:
            raise FileNotFoundException(
                f"Elemento '{name}' não encontrado no diretório '{self.get_path()}'."
            )
        target = self.children[name]
        if isinstance(target, DirectoryNode) and not target.is_empty():
            raise DirectoryNotEmptyException(
                f"Diretório '{target.get_path()}' não está vazio e não pode ser removido."
            )
        removed = self.children.pop(name)
        removed.parent = None
        self.modified_at = time.time()
        return removed

    def get_child(self, name: str) -> Optional[Node]:
        """Lookup child node by name without raising exception."""
        return self.children.get(name)

    def has_child(self, name: str) -> bool:
        """Return True if child exists in this directory."""
        return name in self.children

    def is_empty(self) -> bool:
        """Return True if directory contains no children."""
        return len(self.children) == 0

    def list_children(self) -> List[Node]:
        """Return list of child nodes sorted alphabetically."""
        return sorted(self.children.values(), key=lambda node: (node.node_type != NodeType.DIRECTORY, node.name))

    def format_tree(self, inode_table: Optional[Dict[int, any]] = None, prefix: str = "", is_last: bool = True) -> str:
        """Render directory tree visual hierarchy adhering to official examples."""
        lines: List[str] = []
        if self.parent is None:
            # Root directory header
            lines.append("[ÁRVORE DO SISTEMA DE ARQUIVOS]")
            lines.append("/")
            child_list = self.list_children()
            for idx, child in enumerate(child_list):
                last_item = idx == len(child_list) - 1
                lines.append(child._render_tree(inode_table, "", last_item))
            return "\n".join(lines)
        return self._render_tree(inode_table, prefix, is_last)

    def _render_tree(self, inode_table: Optional[Dict[int, any]], prefix: str, is_last: bool) -> str:
        connector = "└── " if is_last else "├── "
        lines = [f"{prefix}{connector}{self.name}/ [DIR]"]
        new_prefix = prefix + ("    " if is_last else "│   ")
        child_list = self.list_children()
        for idx, child in enumerate(child_list):
            last_item = idx == len(child_list) - 1
            lines.append(child._render_tree(inode_table, new_prefix, last_item))
        return "\n".join(lines)


# Helper rendering for FileNode
def _render_file_tree(self: FileNode, inode_table: Optional[Dict[int, any]], prefix: str, is_last: bool) -> str:
    connector = "└── " if is_last else "├── "
    size_str = ""
    if inode_table and self.inode_id in inode_table:
        inode = inode_table[self.inode_id]
        size_bytes = getattr(inode, "file_size", 0)
        if size_bytes >= 1024 and size_bytes % 1024 == 0:
            size_str = f" ({size_bytes // 1024} KB)"
        elif size_bytes >= 1024:
            size_str = f" ({size_bytes / 1024:.2f} KB)"
        else:
            size_str = f" ({size_bytes} B)"
    return f"{prefix}{connector}{self.name}{size_str} [ARQ]"


FileNode._render_tree = _render_file_tree
