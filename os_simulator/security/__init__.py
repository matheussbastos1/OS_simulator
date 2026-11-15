"""Security and Protection subsystem for OS Simulator (Etapa 3).

This package provides user management, PBKDF2 authentication, POSIX ACLs,
in-memory audit logging, AES-256-GCM data-at-rest encryption, integrity
verification with HMAC catalog signatures, and simulated antivirus scanning.
"""

from os_simulator.core.exceptions import (
    AuthenticationFailedException,
    CryptoKeyException,
    DecryptionFailedException,
    GroupAlreadyExistsException,
    GroupNotFoundException,
    IntegrityException,
    InvalidTagException,
    PermissionDeniedException,
    PrivilegeViolationException,
    SecurityException,
    TamperDetectedException,
    UserAlreadyExistsException,
    UserNotFoundException,
)
from os_simulator.core.ports import AuthorizationPort
from os_simulator.core.types import AuditEventType, FileScanStatus, PrivilegeMode
from os_simulator.security.acl import (
    ACL,
    FilePermissions,
    Permission,
    PermissionTriple,
)
from os_simulator.security.audit import AuditEvent, AuditLog
from os_simulator.security.auth import AuthenticationService
from os_simulator.security.bootstrap import BootstrapSecurityPolicy
from os_simulator.security.crypto import (
    CryptoBlockDeviceAdapter,
    CryptoEngine,
    EncryptedBlockDevicePort,
    EncryptedPayload,
    decrypt_file,
    encrypt_file,
)
from os_simulator.security.integrity import (
    DEFAULT_MALWARE_SIGNATURES,
    SIMULATED_MALWARE_SIGNATURES,
    AntivirusScanReport,
    AntivirusScanner,
    BaselineCatalog,
    FileScanResult,
    IntegrityCheckResult,
    IntegrityChecker,
    IntegrityRecord,
    ScanStatus,
)
from os_simulator.security.service import SecurityManager
from os_simulator.security.user import Group, User, UserManager

__all__ = [
    # Ports and Policies
    "AuthorizationPort",
    "BootstrapSecurityPolicy",
    "SecurityManager",
    # Identity and Authentication
    "User",
    "Group",
    "UserManager",
    "AuthenticationService",
    # ACL and Permissions
    "ACL",
    "FilePermissions",
    "Permission",
    "PermissionTriple",
    # Audit Logging
    "AuditEvent",
    "AuditLog",
    # Cryptography
    "CryptoEngine",
    "EncryptedPayload",
    "CryptoBlockDeviceAdapter",
    "EncryptedBlockDevicePort",
    "encrypt_file",
    "decrypt_file",
    # Integrity and Antivirus
    "IntegrityRecord",
    "IntegrityCheckResult",
    "FileScanResult",
    "AntivirusScanReport",
    "BaselineCatalog",
    "IntegrityChecker",
    "AntivirusScanner",
    "ScanStatus",
    "SIMULATED_MALWARE_SIGNATURES",
    "DEFAULT_MALWARE_SIGNATURES",
    # Core types and Enums
    "PrivilegeMode",
    "AuditEventType",
    "FileScanStatus",
    # Exceptions
    "SecurityException",
    "PermissionDeniedException",
    "AuthenticationFailedException",
    "IntegrityException",
    "TamperDetectedException",
    "DecryptionFailedException",
    "InvalidTagException",
    "CryptoKeyException",
    "UserNotFoundException",
    "UserAlreadyExistsException",
    "GroupNotFoundException",
    "GroupAlreadyExistsException",
    "PrivilegeViolationException",
]
