"""Exception hierarchy for OS Simulator."""

from typing import Optional


class OSSimulatorException(Exception):
    """Base exception for all OS Simulator errors."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__

    def __str__(self) -> str:
        return self.message


# Filesystem Exceptions
class FileSystemException(OSSimulatorException):
    """Base class for filesystem errors."""
    pass


class FileNotFoundException(FileSystemException):
    """Raised when a file or directory path cannot be resolved."""
    pass


class FileAlreadyExistsException(FileSystemException):
    """Raised when attempting to create a node that already exists."""
    pass


class IsADirectoryException(FileSystemException):
    """Raised when an operation expected a file but found a directory."""
    pass


class NotADirectoryException(FileSystemException):
    """Raised when an operation expected a directory but found a file."""
    pass


class DirectoryNotEmptyException(FileSystemException):
    """Raised when attempting to remove a non-empty directory."""
    pass


class InvalidPathException(FileSystemException):
    """Raised when a path string is malformed or invalid."""
    pass


class InodeTableExhaustedException(FileSystemException):
    """Raised when no free i-nodes are available in the table."""
    pass


# Storage & Device Exceptions
class StorageException(OSSimulatorException):
    """Base class for storage and block device errors."""
    pass


class DiskFullException(StorageException):
    """Raised when disk capacity is exhausted."""
    pass


class DiskFragmentationException(StorageException):
    """Raised when contiguous free space cannot satisfy allocation."""
    pass


class InvalidBlockException(StorageException):
    """Raised when accessing an out-of-bounds or invalid block ID."""
    pass


# Security & Authorization Exceptions
class SecurityException(OSSimulatorException):
    """Base class for security and access control errors."""
    pass


class PermissionDeniedException(SecurityException):
    """Raised when access is blocked due to insufficient permissions."""
    pass


class AuthenticationFailedException(SecurityException):
    """Raised when credentials verification fails."""
    pass


class IntegrityException(SecurityException):
    """Base class for integrity, hash, and tampering errors."""
    pass


class TamperDetectedException(IntegrityException):
    """Raised when unauthorized modification or tampering is detected."""
    pass


class DecryptionFailedException(SecurityException):
    """Raised when authenticated decryption fails (invalid tag, bad key, or tampered ciphertext)."""
    pass


class UserNotFoundException(SecurityException):
    """Raised when a specified user does not exist."""
    pass


class UserAlreadyExistsException(SecurityException):
    """Raised when attempting to create a user that already exists."""
    pass


class GroupNotFoundException(SecurityException):
    """Raised when a specified group does not exist."""
    pass


class GroupAlreadyExistsException(SecurityException):
    """Raised when attempting to create a group that already exists."""
    pass


class PrivilegeViolationException(SecurityException):
    """Raised when an unauthorized privilege ring escalation is attempted."""
    pass


class InvalidTagException(DecryptionFailedException, AuthenticationFailedException):
    """Raised when cryptographic authentication tag verification fails (e.g. data tampering)."""
    pass


class CryptoKeyException(SecurityException):
    """Raised when an encryption key is invalid, missing, or improperly sized."""
    pass


# Process & Execution Exceptions (Etapa 4)
class ProcessException(OSSimulatorException):
    """Base class for process lifecycle errors."""
    pass


class ProcessNotFoundException(ProcessException):
    """Raised when a process PID or name cannot be located."""
    pass


class ProcessAlreadyExistsException(ProcessException):
    """Raised when attempting to create a process with an existing name/PID."""
    pass


class InvalidProcessStateException(ProcessException):
    """Raised when an operation is invalid for current process state."""
    pass


# Memory Management Exceptions (Etapa 4)
class MemoryException(OSSimulatorException):
    """Base class for memory subsystem errors."""
    pass


class OutOfMemoryException(MemoryException):
    """Raised when memory capacity (reserved, dynamic, or swap) is exhausted."""
    pass


class MemoryFragmentationException(MemoryException):
    """Raised when contiguous memory allocation fails due to external fragmentation."""
    pass


class PageFaultException(MemoryException):
    """Raised by MMU when a logical page is not present in physical RAM."""

    def __init__(self, pid: int, logical_page: int, page_origin: str = "ZERO_FILL_ON_DEMAND", message: Optional[str] = None):
        msg = message or f"Falta de página (Page Fault): Processo {pid}, Página Lógica {logical_page} (Origem: {page_origin})"
        super().__init__(msg, code="PAGE_FAULT")
        self.pid = pid
        self.logical_page = logical_page
        self.page_origin = page_origin


class InvalidAddressException(MemoryException):
    """Raised when an address or logical page is out of bounds for the process."""
    pass


class SwapException(MemoryException):
    """Base class for swap storage errors."""
    pass


class SwapFullException(SwapException):
    """Raised when the simulated swap partition runs out of free slots."""
    pass


