"""Virtual File System (VFS) path resolution and directory tree operations."""

from typing import List, Optional, Tuple

from os_simulator.core.exceptions import (
    DirectoryNotEmptyException,
    FileAlreadyExistsException,
    FileNotFoundException,
    InvalidPathException,
    IsADirectoryException,
    NotADirectoryException,
)
from os_simulator.core.types import NodeType
from os_simulator.filesystem.node import DirectoryNode, FileNode, Node


class VirtualFileSystem:
    """Manages the in-memory directory hierarchy and path resolution."""

    def __init__(self, root_inode_id: int = 1):
        self.root: DirectoryNode = DirectoryNode("/", inode_id=root_inode_id, parent=None)

    def normalize_path(self, path: str, cwd: str = "/") -> str:
        """Resolve relative and absolute paths into a canonical path."""
        if not path or not path.strip():
            raise InvalidPathException("Caminho não pode ser vazio.")

        path = path.strip()
        is_absolute = path.startswith("/")

        if is_absolute:
            combined = path
        else:
            base = cwd if cwd.endswith("/") else f"{cwd}/"
            combined = f"{base}{path}"

        parts = [p for p in combined.split("/") if p and p != "."]
        stack: List[str] = []

        for part in parts:
            if part == "..":
                if stack:
                    stack.pop()
            else:
                stack.append(part)

        return "/" + "/".join(stack)

    def split_path(self, canonical_path: str) -> Tuple[str, str]:
        """Split a canonical path into (parent_dir_path, node_name)."""
        if canonical_path == "/":
            return "/", "/"
        parts = canonical_path.rstrip("/").split("/")
        name = parts[-1]
        parent_path = "/".join(parts[:-1]) or "/"
        return parent_path, name

    def get_node(self, path: str, cwd: str = "/") -> Optional[Node]:
        """Traverse tree and return Node at path, or None if not found."""
        canonical = self.normalize_path(path, cwd)
        if canonical == "/":
            return self.root

        current: Node = self.root
        parts = [p for p in canonical.split("/") if p]

        for part in parts:
            if not isinstance(current, DirectoryNode):
                return None
            child = current.get_child(part)
            if child is None:
                return None
            current = child

        return current

    def get_node_or_raise(self, path: str, cwd: str = "/") -> Node:
        """Traverse tree and return Node, raising FileNotFoundException if missing."""
        node = self.get_node(path, cwd)
        if node is None:
            raise FileNotFoundException(f"Caminho não encontrado: '{path}'.")
        return node

    def get_directory(self, path: str, cwd: str = "/") -> DirectoryNode:
        """Return DirectoryNode at path, validating it is indeed a directory."""
        node = self.get_node_or_raise(path, cwd)
        if not isinstance(node, DirectoryNode):
            raise NotADirectoryException(f"Caminho não é um diretório: '{path}'.")
        return node

    def get_file(self, path: str, cwd: str = "/") -> FileNode:
        """Return FileNode at path, validating it is indeed a file."""
        node = self.get_node_or_raise(path, cwd)
        if not isinstance(node, FileNode):
            raise IsADirectoryException(f"Caminho é um diretório, esperava arquivo: '{path}'.")
        return node

    def exists(self, path: str, cwd: str = "/") -> bool:
        """Check if path exists in tree."""
        return self.get_node(path, cwd) is not None

    def mkdir(
        self,
        path: str,
        inode_id: int,
        cwd: str = "/",
        create_parents: bool = False,
    ) -> DirectoryNode:
        """Create a new directory at path."""
        canonical = self.normalize_path(path, cwd)
        if canonical == "/":
            raise FileAlreadyExistsException("Diretório raiz '/' já existe.")

        parent_path, dir_name = self.split_path(canonical)
        parent_node = self.get_node(parent_path)

        if parent_node is None:
            if create_parents:
                raise NotImplementedError("Criação recursiva de pais deve ser gerenciada pelo serviço.")
            raise FileNotFoundException(f"Diretório pai '{parent_path}' não existe.")

        if not isinstance(parent_node, DirectoryNode):
            raise NotADirectoryException(f"Caminho pai '{parent_path}' não é um diretório.")

        if parent_node.has_child(dir_name):
            raise FileAlreadyExistsException(f"Diretório ou arquivo '{dir_name}' já existe em '{parent_path}'.")

        new_dir = DirectoryNode(dir_name, inode_id=inode_id, parent=parent_node)
        parent_node.add_child(new_dir)
        return new_dir

    def create_file(self, path: str, inode_id: int, cwd: str = "/") -> FileNode:
        """Create a new file node in the hierarchy."""
        canonical = self.normalize_path(path, cwd)
        if canonical == "/":
            raise IsADirectoryException("Não é possível criar um arquivo com nome '/'.")

        parent_path, file_name = self.split_path(canonical)
        parent_node = self.get_node(parent_path)

        if parent_node is None:
            raise FileNotFoundException(f"Diretório pai '{parent_path}' não existe.")

        if not isinstance(parent_node, DirectoryNode):
            raise NotADirectoryException(f"Caminho pai '{parent_path}' não é um diretório.")

        if parent_node.has_child(file_name):
            raise FileAlreadyExistsException(f"Arquivo ou diretório '{file_name}' já existe em '{parent_path}'.")

        new_file = FileNode(file_name, inode_id=inode_id, parent=parent_node)
        parent_node.add_child(new_file)
        return new_file

    def delete_file(self, path: str, cwd: str = "/") -> int:
        """Remove a file node and return its associated inode_id."""
        canonical = self.normalize_path(path, cwd)
        parent_path, file_name = self.split_path(canonical)
        parent = self.get_directory(parent_path)

        target = parent.get_child(file_name)
        if target is None:
            raise FileNotFoundException(f"Arquivo não encontrado: '{path}'.")
        if isinstance(target, DirectoryNode):
            raise IsADirectoryException(f"'{path}' é um diretório, utilize delete_directory.")

        removed = parent.remove_child(file_name)
        return removed.inode_id

    def delete_directory(self, path: str, cwd: str = "/") -> int:
        """Remove an empty directory and return its associated inode_id."""
        canonical = self.normalize_path(path, cwd)
        if canonical == "/":
            raise PermissionError("Não é permitido excluir o diretório raiz '/'.")

        parent_path, dir_name = self.split_path(canonical)
        parent = self.get_directory(parent_path)

        target = parent.get_child(dir_name)
        if target is None:
            raise FileNotFoundException(f"Diretório não encontrado: '{path}'.")
        if not isinstance(target, DirectoryNode):
            raise NotADirectoryException(f"'{path}' não é um diretório.")
        if not target.is_empty():
            raise DirectoryNotEmptyException(f"Diretório '{canonical}' contém elementos e não pode ser excluído.")

        removed = parent.remove_child(dir_name)
        return removed.inode_id
