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
