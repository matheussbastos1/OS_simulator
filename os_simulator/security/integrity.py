"""Integrity verification and simulated antivirus subsystem for OS Simulator (Etapa 3).

Provides SHA-256 integrity calculation, an official Kernel HMAC-signed BaselineCatalog,
tamper detection down to individual physical storage blocks, and recursive antivirus
scanning with educational malware signatures and visual report generation.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import (
    DecryptionFailedException,
    FileNotFoundException,
    IntegrityException,
    InvalidTagException,
    PermissionDeniedException,
    SecurityException,
    TamperDetectedException,
)
from os_simulator.core.ports import AuthorizationPort, BlockDevicePort
from os_simulator.core.types import AuditEventType, FileScanStatus, NodeType
from os_simulator.security.audit import AuditEvent, AuditLog

# Alias for compatibility with external references
ScanStatus = FileScanStatus

# Official educational malware signatures
SIMULATED_MALWARE_SIGNATURES: Dict[str, str] = {
    "SIM_MALWARE_TROJAN_PAYLOAD": "Trojan.Simulator.Generic",
    "SIM_MALWARE_VIRUS_SIG_01": "Virus.Academic.BlockTamper",
    "SIM_RANSOM_SAMPLE_TEST": "Ransom.Simulator.LockTest",
    "SIM_SPYWARE_KEYLOGGER": "Spyware.Simulator.KeyLogger",
    "SIM_ROOTKIT_HOOK_SIG": "Rootkit.Simulator.KernelHook",
    "SIM_EICAR_STANDARD_TEST": "EICAR.Standard.Antivirus.Test",
}

DEFAULT_MALWARE_SIGNATURES: Dict[str, str] = SIMULATED_MALWARE_SIGNATURES

# Portuguese display labels for visual reports
STATUS_DISPLAY_LABELS: Dict[FileScanStatus, str] = {
    FileScanStatus.OK: "OK",
    FileScanStatus.OK_ENCRYPTED: "OK_ENCRYPTED",
    FileScanStatus.MODIFIED: "MODIFICADO",
    FileScanStatus.SUSPICIOUS: "SUSPEITO",
    FileScanStatus.INACCESSIBLE: "INACESSIVEL",
}


@dataclass
class IntegrityRecord:
    """Official tamper-evident baseline record for a filesystem resource.

    Attributes:
        resource_path: Canonical path of monitored file.
        expected_sha256: Expected SHA-256 hash of file content/payload.
        hmac_signature: Kernel-signed HMAC-SHA256 signature protecting the record.
        last_verified: Timestamp of last successful verification.
        block_hashes: Mapping of block_id -> SHA-256 hash of physical block content.
        is_encrypted: Whether the file payload is encrypted at rest.
        file_size: Size of file in bytes when baseline was registered.
    """

    resource_path: str
    expected_sha256: str
    hmac_signature: str
    last_verified: float = field(default_factory=time.time)
    block_hashes: Dict[int, str] = field(default_factory=dict)
    is_encrypted: bool = False
    file_size: int = 0

    def compute_expected_hmac(self, kernel_secret: bytes) -> str:
        """Compute expected HMAC-SHA256 signature over record canonical representation."""
        canonical = f"{self.resource_path}:{self.expected_sha256}:{self.file_size}:{int(self.is_encrypted)}".encode(
            "utf-8"
        )
        return hmac.new(kernel_secret, canonical, hashlib.sha256).hexdigest()

    def verify_signature(self, kernel_secret: bytes) -> bool:
        """Verify HMAC signature using protected kernel secret."""
        sig1 = self.compute_expected_hmac(kernel_secret)
        if hmac.compare_digest(self.hmac_signature, sig1):
            return True
        # Also support fallback canonical format resource_path:expected_sha256
        sig2 = hmac.new(
            kernel_secret,
            f"{self.resource_path}:{self.expected_sha256}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.hmac_signature, sig2)

    def is_valid(self, kernel_secret: bytes) -> bool:
        """Alias for verify_signature."""
        return self.verify_signature(kernel_secret)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dictionary."""
        return {
            "resource_path": self.resource_path,
            "expected_sha256": self.expected_sha256,
            "hmac_signature": self.hmac_signature,
            "last_verified": self.last_verified,
            "block_hashes": dict(self.block_hashes),
            "is_encrypted": self.is_encrypted,
            "file_size": self.file_size,
        }


@dataclass
class IntegrityCheckResult:
    """Detailed result of an integrity check operation on a file."""

    path: str
    is_valid: bool
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    hmac_valid: bool = True
    tampered_blocks: List[int] = field(default_factory=list)
    is_encrypted: bool = False
    error_message: Optional[str] = None


class BaselineCatalog:
    """Official baseline registry of expected file and block hashes.

    Protected with Kernel HMAC signatures so unauthorized users cannot alter
    the official baseline without the protected kernel secret.
    """

    def __init__(self, kernel_secret: Optional[bytes] = None) -> None:
        self.kernel_secret: bytes = kernel_secret or secrets.token_bytes(32)
        self.records: Dict[str, IntegrityRecord] = {}
        self._catalog_hmac: str = self._compute_catalog_hmac()

    def _compute_catalog_hmac(self) -> str:
        """Calculate HMAC over all sorted records in catalog."""
        items = []
        for path in sorted(self.records.keys()):
            r = self.records[path]
            items.append(f"{r.resource_path}:{r.expected_sha256}:{r.hmac_signature}")
        raw = "\n".join(items).encode("utf-8")
        return hmac.new(self.kernel_secret, raw, hashlib.sha256).hexdigest()

    def register(
        self,
        resource_path: str,
        expected_sha256: str,
        block_hashes: Optional[Dict[int, str]] = None,
        is_encrypted: bool = False,
        file_size: int = 0,
    ) -> IntegrityRecord:
        """Register or update an official baseline record for a resource."""
        canonical_path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
        record = IntegrityRecord(
            resource_path=canonical_path,
            expected_sha256=expected_sha256,
            hmac_signature="",
            last_verified=time.time(),
            block_hashes=dict(block_hashes or {}),
            is_encrypted=is_encrypted,
            file_size=file_size,
        )
        record.hmac_signature = record.compute_expected_hmac(self.kernel_secret)
        self.records[canonical_path] = record
        self._catalog_hmac = self._compute_catalog_hmac()
        return record

    def register_record(self, record: IntegrityRecord) -> None:
        """Register an existing IntegrityRecord directly."""
        if not record.hmac_signature:
            record.hmac_signature = record.compute_expected_hmac(self.kernel_secret)
        self.records[record.resource_path] = record
        self._catalog_hmac = self._compute_catalog_hmac()

    def get(self, resource_path: str) -> Optional[IntegrityRecord]:
        """Retrieve record by canonical path."""
        canonical_path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
        return self.records.get(canonical_path)

    def get_record(self, resource_path: str) -> Optional[IntegrityRecord]:
        """Alias for get()."""
        return self.get(resource_path)

    def has_record(self, resource_path: str) -> bool:
        """Check if record exists for path."""
        canonical_path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
        return canonical_path in self.records

    def __contains__(self, resource_path: str) -> bool:
        return self.has_record(resource_path)

    def remove(self, resource_path: str) -> Optional[IntegrityRecord]:
        """Remove record from baseline catalog."""
        canonical_path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
        removed = self.records.pop(canonical_path, None)
        if removed is not None:
            self._catalog_hmac = self._compute_catalog_hmac()
        return removed

    def remove_record(self, resource_path: str) -> Optional[IntegrityRecord]:
        """Alias for remove()."""
        return self.remove(resource_path)

    def verify_record_hmac(self, resource_path: str) -> bool:
        """Verify the HMAC signature of an individual record."""
        record = self.get(resource_path)
        if record is None:
            return False
        return record.verify_signature(self.kernel_secret)

    def verify_catalog_hmac(self) -> bool:
        """Verify the global catalog HMAC signature."""
        current = self._compute_catalog_hmac()
        return hmac.compare_digest(current, self._catalog_hmac)

    def verify_catalog(self) -> Tuple[bool, List[str]]:
        """Verify global catalog integrity and individual record HMAC signatures.

        Returns:
            Tuple of (is_all_valid, list_of_tampered_resource_paths).
        """
        tampered_paths: List[str] = []
        for path, record in self.records.items():
            if not record.verify_signature(self.kernel_secret):
                tampered_paths.append(path)

        global_hmac_valid = self.verify_catalog_hmac()
        all_valid = (len(tampered_paths) == 0) and global_hmac_valid
        return all_valid, tampered_paths

    def list_records(self) -> List[IntegrityRecord]:
        """Return list of all registered baseline records."""
        return list(self.records.values())

    def clear(self) -> None:
        """Clear all records from catalog."""
        self.records.clear()
        self._catalog_hmac = self._compute_catalog_hmac()

    def __len__(self) -> int:
        return len(self.records)

    def __bool__(self) -> bool:
        """Ensure catalog evaluates to True even when empty."""
        return True


class IntegrityChecker:
    """Performs SHA-256 calculation for file contents and storage blocks,
    and validates them against the official BaselineCatalog.
    """

    @staticmethod
    def compute_sha256(data: bytes | bytearray | str) -> str:
        """Calculate SHA-256 hexadecimal digest of input data."""
        if isinstance(data, str):
            raw = data.encode("utf-8")
        elif isinstance(data, bytearray):
            raw = bytes(data)
        else:
            raw = data
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def compute_block_sha256(device: BlockDevicePort, block_id: int) -> str:
        """Read physical block and compute SHA-256 hash."""
        data = device.read_block(block_id)
        return IntegrityChecker.compute_sha256(data)

    def compute_file_content_sha256(self, fs_service: Any, path: str, cwd: str = "/") -> str:
        """Read file raw payload from filesystem and compute SHA-256 hash."""
        raw_bytes = fs_service.read_file_bytes(path, cwd=cwd)
        return self.compute_sha256(raw_bytes)

    def compute_file_block_hashes(self, fs_service: Any, path: str, cwd: str = "/") -> Dict[int, str]:
        """Compute SHA-256 hash of each block currently allocated to the file."""
        node = fs_service.vfs.get_file(path, cwd=cwd)
        inode = fs_service.inode_table[node.inode_id]
        block_hashes: Dict[int, str] = {}
        for b_id in inode.allocated_blocks:
            blk_data = fs_service.device.read_block(b_id)
            block_hashes[b_id] = self.compute_sha256(blk_data)
        return block_hashes

    def register_file_baseline(
        self,
        fs_service: Any,
        path: str,
        catalog: BaselineCatalog,
        cwd: str = "/",
    ) -> IntegrityRecord:
        """Generate baseline hashes for file and register in catalog.

        Also records the content hash in inode.integrity_hash.
        """
        node = fs_service.vfs.get_file(path, cwd=cwd)
        inode = fs_service.inode_table[node.inode_id]
        canonical_path = node.get_path()

        from os_simulator.filesystem.allocation import AllocationStrategyFactory

        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)
        payload = strategy_handler.read_data(fs_service.device, inode)
        content_hash = self.compute_sha256(payload)

        block_hashes = {}
        for b_id in inode.allocated_blocks:
            blk_data = fs_service.device.read_block(b_id)
            block_hashes[b_id] = self.compute_sha256(blk_data)

        inode.integrity_hash = content_hash
        is_encrypted = getattr(inode, "is_encrypted", False)

        return catalog.register(
            resource_path=canonical_path,
            expected_sha256=content_hash,
            block_hashes=block_hashes,
            is_encrypted=is_encrypted,
            file_size=len(payload),
        )

    def register_tree_baseline(
        self,
        fs_service: Any,
        catalog: BaselineCatalog,
        root_path: str = "/",
        cwd: str = "/",
    ) -> int:
        """Recursively generate baseline for all files starting from root_path."""
        root_node = fs_service.vfs.get_node(root_path, cwd=cwd)
        if root_node is None:
            raise FileNotFoundException(f"Caminho '{root_path}' não encontrado.")

        count = 0

        def _walk(node: Any):
            nonlocal count
            if node.node_type == NodeType.FILE:
                self.register_file_baseline(fs_service, node.get_path(), catalog)
                count += 1
            elif node.node_type == NodeType.DIRECTORY:
                for child in node.list_children():
                    _walk(child)

        _walk(root_node)
        return count

    def verify_file(
        self,
        fs_service: Any,
        path: str,
        catalog: BaselineCatalog,
        cwd: str = "/",
    ) -> IntegrityCheckResult:
        """Verify integrity of a file against BaselineCatalog."""
        node = fs_service.vfs.get_file(path, cwd=cwd)
        inode = fs_service.inode_table[node.inode_id]
        canonical_path = node.get_path()
        is_encrypted = getattr(inode, "is_encrypted", False)

        record = catalog.get(canonical_path)
        if record is None:
            # No baseline registered in catalog: check inode.integrity_hash if present
            from os_simulator.filesystem.allocation import AllocationStrategyFactory

            strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)
            try:
                payload = strategy_handler.read_data(fs_service.device, inode)
                actual_hash = self.compute_sha256(payload)
            except Exception:
                actual_hash = None

            if inode.integrity_hash is not None and actual_hash != inode.integrity_hash:
                return IntegrityCheckResult(
                    path=canonical_path,
                    is_valid=False,
                    expected_hash=inode.integrity_hash,
                    actual_hash=actual_hash,
                    hmac_valid=True,
                    tampered_blocks=[],
                    is_encrypted=is_encrypted,
                    error_message="Hash diverge do integrity_hash registrado no i-node.",
                )

            return IntegrityCheckResult(
                path=canonical_path,
                is_valid=True,
                expected_hash=None,
                actual_hash=actual_hash,
                hmac_valid=True,
                tampered_blocks=[],
                is_encrypted=is_encrypted,
                error_message="Arquivo sem baseline cadastrado no catálogo.",
            )

        # 1. Check HMAC signature of the record
        if not record.verify_signature(catalog.kernel_secret):
            return IntegrityCheckResult(
                path=canonical_path,
                is_valid=False,
                expected_hash=record.expected_sha256,
                actual_hash=None,
                hmac_valid=False,
                tampered_blocks=[],
                is_encrypted=is_encrypted,
                error_message="Assinatura HMAC do Kernel inválida! Adulteração do registro de baseline detectada.",
            )

        # 2. Check individual physical blocks
        tampered_blocks: List[int] = []
        for b_id, expected_b_hash in record.block_hashes.items():
            try:
                blk_data = fs_service.device.read_block(b_id)
                actual_b_hash = self.compute_sha256(blk_data)
                if actual_b_hash != expected_b_hash:
                    tampered_blocks.append(b_id)
            except Exception:
                tampered_blocks.append(b_id)

        # 3. Check payload hash
        from os_simulator.filesystem.allocation import AllocationStrategyFactory

        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)
        actual_hash: Optional[str] = None
        read_failed = False
        error_msg: Optional[str] = None

        try:
            payload = strategy_handler.read_data(fs_service.device, inode)
            actual_hash = self.compute_sha256(payload)
        except (InvalidTagException, DecryptionFailedException) as e:
            read_failed = True
            error_msg = f"Falha de autenticação criptográfica (tag inválida): {e}"
        except Exception as e:
            read_failed = True
            error_msg = f"Falha ao ler dados do arquivo: {e}"

        hash_matches = (actual_hash == record.expected_sha256) if actual_hash is not None else False
        is_valid = (len(tampered_blocks) == 0) and hash_matches and not read_failed

        if is_valid:
            record.last_verified = time.time()
        elif error_msg is None:
            if tampered_blocks and not hash_matches:
                error_msg = f"Adulteração detectada no bloco {tampered_blocks} e divergência de hash geral."
            elif tampered_blocks:
                error_msg = f"Adulteração física detectada no(s) bloco(s) {tampered_blocks}."
            else:
                error_msg = (
                    f"Divergência de hash de conteúdo: esperado {record.expected_sha256}, obtido {actual_hash}."
                )

        return IntegrityCheckResult(
            path=canonical_path,
            is_valid=is_valid,
            expected_hash=record.expected_sha256,
            actual_hash=actual_hash,
            hmac_valid=True,
            tampered_blocks=tampered_blocks,
            is_encrypted=is_encrypted,
            error_message=error_msg,
        )


@dataclass
class FileScanResult:
    """Inspection result for a single file during antivirus scanning."""

    path: str
    status: FileScanStatus
    matched_signatures: List[str] = field(default_factory=list)
    tampered_blocks: List[int] = field(default_factory=list)
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    hmac_valid: bool = True
    is_encrypted: bool = False
    size_bytes: int = 0
    details: str = ""

    @property
    def display_status(self) -> str:
        """Return Portuguese status display label."""
        return STATUS_DISPLAY_LABELS.get(self.status, self.status.value)


@dataclass
class AntivirusScanReport:
    """Consolidated summary of an antivirus and integrity scan."""

    target_path: str
    results: List[FileScanResult] = field(default_factory=list)
    total_files: int = 0
    ok_count: int = 0
    ok_encrypted_count: int = 0
    modified_count: int = 0
    suspicious_count: int = 0
    inaccessible_count: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    def add_result(self, res: FileScanResult) -> None:
        """Add a file result and increment appropriate status counters."""
        self.results.append(res)
        self.total_files += 1
        if res.status == FileScanStatus.OK:
            self.ok_count += 1
        elif res.status == FileScanStatus.OK_ENCRYPTED:
            self.ok_encrypted_count += 1
        elif res.status == FileScanStatus.MODIFIED:
            self.modified_count += 1
        elif res.status == FileScanStatus.SUSPICIOUS:
            self.suspicious_count += 1
        elif res.status == FileScanStatus.INACCESSIBLE:
            self.inaccessible_count += 1

    @property
    def has_threats(self) -> bool:
        """Return True if any modified (tampered) or suspicious (malware) files were found."""
        return self.modified_count > 0 or self.suspicious_count > 0

    @property
    def tampered_files(self) -> List[FileScanResult]:
        """Return list of modified/tampered file results."""
        return [r for r in self.results if r.status == FileScanStatus.MODIFIED]

    @property
    def suspicious_files(self) -> List[FileScanResult]:
        """Return list of suspicious/malware file results."""
        return [r for r in self.results if r.status == FileScanStatus.SUSPICIOUS]

    def format_report(self) -> str:
        """Format the visual report matching official academic output standards."""
        lines = [
            "======================================================================",
            "                  RELATÓRIO DO ANTIVÍRUS E INTEGRIDADE",
            "======================================================================",
            f"Diretório Base Analisado     : {self.target_path}",
            f"Total de Arquivos Verificados: {self.total_files}",
            f"Arquivos Íntegros (OK)       : {self.ok_count}",
            f"Arquivos Cifrados (OK)       : {self.ok_encrypted_count}",
            f"Arquivos Modificados         : {self.modified_count}",
            f"Arquivos Suspeitos (Malware) : {self.suspicious_count}",
            f"Arquivos Inacessíveis        : {self.inaccessible_count}",
            "----------------------------------------------------------------------",
            "Detalhes da Verificação:",
        ]

        if not self.results:
            lines.append("  Nenhum arquivo encontrado para verificação.")
        else:
            for r in self.results:
                label = f"[{r.display_status}]"
                if r.status == FileScanStatus.OK:
                    hash_disp = f" (Hash: {r.actual_hash[:16]}...)" if r.actual_hash else ""
                    lines.append(f"  {label:<16} {r.path}{hash_disp}")
                elif r.status == FileScanStatus.OK_ENCRYPTED:
                    hash_disp = f" (Hash: {r.actual_hash[:16]}...)" if r.actual_hash else ""
                    lines.append(f"  {label:<16} {r.path}{hash_disp} [AES-256-GCM]")
                elif r.status == FileScanStatus.MODIFIED:
                    lines.append(f"  {label:<16} {r.path} - ALERTA: Divergência de integridade detectada!")
                    if r.expected_hash and r.actual_hash:
                        lines.append(f"                   Hash Esperado: {r.expected_hash}")
                        lines.append(f"                   Hash Atual   : {r.actual_hash}")
                    elif r.expected_hash:
                        lines.append(f"                   Hash Esperado: {r.expected_hash}")
                    if r.tampered_blocks:
                        lines.append(f"                   Bloco(s) Adulterado(s): {r.tampered_blocks}")
                    if r.details:
                        lines.append(f"                   Detalhe: {r.details}")
                elif r.status == FileScanStatus.SUSPICIOUS:
                    sigs_str = ", ".join(r.matched_signatures) if r.matched_signatures else "Assinatura desconhecida"
                    lines.append(f"  {label:<16} {r.path} - ALERTA: Assinatura de ameaça detectada!")
                    lines.append(f"                   Ameaça(s): {sigs_str}")
                elif r.status == FileScanStatus.INACCESSIBLE:
                    lines.append(f"  {label:<16} {r.path} - Acesso negado por permissões de leitura.")

        lines.append("======================================================================")
        return "\n".join(lines)


class AntivirusScanner:
    """Recursive filesystem scanner and malware detection engine."""

    def __init__(
        self,
        fs_service: Any,
        catalog: Optional[BaselineCatalog] = None,
        signatures: Optional[Dict[str, Union[str, bytes]]] = None,
        auth_port: Optional[AuthorizationPort] = None,
        audit_log: Optional[AuditLog] = None,
        checker: Optional[IntegrityChecker] = None,
        kernel_secret: Optional[bytes] = None,
    ) -> None:
        self.fs_service = fs_service
        self.kernel_secret = kernel_secret or (catalog.kernel_secret if catalog is not None else secrets.token_bytes(32))
        self.catalog = catalog if catalog is not None else BaselineCatalog(kernel_secret=self.kernel_secret)
        self.checker = checker if checker is not None else IntegrityChecker()
        self.auth_port = auth_port if auth_port is not None else getattr(fs_service, "auth", None)
        self.audit_log = audit_log if audit_log is not None else getattr(self.auth_port, "audit_log", None)

        # Build signatures dictionary
        self.signatures: Dict[str, str] = dict(SIMULATED_MALWARE_SIGNATURES)
        if signatures is not None:
            for k, v in signatures.items():
                self.signatures[k] = str(v)

    def add_signature(self, token_or_name: str, description_or_pattern: str = "") -> None:
        """Add or update a malware signature definition."""
        self.signatures[token_or_name] = description_or_pattern or token_or_name

    def remove_signature(self, token_or_name: str) -> bool:
        """Remove a signature by key."""
        return self.signatures.pop(token_or_name, None) is not None

    def scan_file(
        self,
        path: str,
        context: Optional[ExecutionContext] = None,
        cwd: str = "/",
    ) -> FileScanResult:
        """Inspect a single file: verify permissions, malware signatures, and baseline integrity."""
        node = self.fs_service.vfs.get_file(path, cwd=cwd)
        inode = self.fs_service.inode_table[node.inode_id]
        canonical_path = node.get_path()
        is_encrypted = getattr(inode, "is_encrypted", False)

        # 1. Authorization check
        if context is not None and self.auth_port is not None:
            can_read = True
            try:
                can_read = self.auth_port.check_read(context, canonical_path, inode)
            except TypeError:
                can_read = self.auth_port.check_read(context, canonical_path)
            except PermissionDeniedException:
                can_read = False
            except Exception:
                can_read = False

            if not can_read:
                if self.audit_log is not None:
                    try:
                        self.audit_log.log_event(
                            event_type=AuditEventType.ACCESS_DENIED,
                            username=context.username,
                            path=canonical_path,
                            action="ANTIVIRUS_SCAN_READ",
                            result="DENIED",
                            details={"reason": "Permissão de leitura negada durante varredura."},
                        )
                    except Exception:
                        pass

                return FileScanResult(
                    path=canonical_path,
                    status=FileScanStatus.INACCESSIBLE,
                    is_encrypted=is_encrypted,
                    size_bytes=inode.file_size,
                    details="Permissão de leitura negada.",
                )

        # 2. Read file data from blocks
        from os_simulator.filesystem.allocation import AllocationStrategyFactory

        strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)

        raw_payload: Optional[bytes] = None
        read_error: Optional[str] = None

        try:
            raw_payload = bytes(strategy_handler.read_data(self.fs_service.device, inode))
        except (InvalidTagException, DecryptionFailedException) as e:
            read_error = f"Falha de autenticação AEAD: {e}"
        except Exception as e:
            read_error = f"Erro de leitura: {e}"

        # 3. Check for malware signatures in the payload or raw blocks
        matched_sigs: List[str] = []
        if raw_payload is not None:
            for sig_key, sig_desc in self.signatures.items():
                pattern_bytes = sig_key.encode("utf-8")
                if pattern_bytes in raw_payload:
                    matched_sigs.append(f"{sig_key} ({sig_desc})" if sig_desc != sig_key else sig_key)
                elif sig_desc and sig_desc.encode("utf-8") in raw_payload:
                    matched_sigs.append(sig_desc)

        # If file is encrypted and payload could not be decrypted or read directly,
        # also inspect raw physical blocks for signatures
        if not matched_sigs and inode.allocated_blocks:
            for b_id in inode.allocated_blocks:
                try:
                    blk_bytes = bytes(self.fs_service.device.read_block(b_id))
                    for sig_key, sig_desc in self.signatures.items():
                        pattern_bytes = sig_key.encode("utf-8")
                        if pattern_bytes in blk_bytes:
                            threat_label = f"{sig_key} ({sig_desc})" if sig_desc != sig_key else sig_key
                            if threat_label not in matched_sigs:
                                matched_sigs.append(threat_label)
                except Exception:
                    pass

        # 4. Check baseline integrity via IntegrityChecker
        integrity_res = self.checker.verify_file(self.fs_service, canonical_path, self.catalog)

        # 5. Classify status based on inspection results
        if matched_sigs:
            status = FileScanStatus.SUSPICIOUS
            if self.audit_log is not None:
                try:
                    self.audit_log.log_event(
                        event_type=AuditEventType.TAMPER_DETECTED,
                        username=context.username if context else "kernel",
                        path=canonical_path,
                        action="ANTIVIRUS_SCAN",
                        result="SUSPICIOUS",
                        details={"threats": matched_sigs},
                    )
                except Exception:
                    pass

            return FileScanResult(
                path=canonical_path,
                status=status,
                matched_signatures=matched_sigs,
                tampered_blocks=integrity_res.tampered_blocks,
                expected_hash=integrity_res.expected_hash,
                actual_hash=integrity_res.actual_hash,
                hmac_valid=integrity_res.hmac_valid,
                is_encrypted=is_encrypted,
                size_bytes=inode.file_size,
                details=f"Assinatura(s) de ameaça detectada(s): {', '.join(matched_sigs)}",
            )

        if not integrity_res.is_valid or read_error is not None:
            status = FileScanStatus.MODIFIED
            if self.audit_log is not None:
                try:
                    self.audit_log.log_event(
                        event_type=AuditEventType.TAMPER_DETECTED,
                        username=context.username if context else "kernel",
                        path=canonical_path,
                        action="INTEGRITY_CHECK",
                        result="TAMPER_DETECTED",
                        details={
                            "tampered_blocks": integrity_res.tampered_blocks,
                            "expected_hash": integrity_res.expected_hash,
                            "actual_hash": integrity_res.actual_hash,
                            "hmac_valid": integrity_res.hmac_valid,
                            "error": read_error,
                        },
                    )
                except Exception:
                    pass

            return FileScanResult(
                path=canonical_path,
                status=status,
                tampered_blocks=integrity_res.tampered_blocks,
                expected_hash=integrity_res.expected_hash,
                actual_hash=integrity_res.actual_hash,
                hmac_valid=integrity_res.hmac_valid,
                is_encrypted=is_encrypted,
                size_bytes=inode.file_size,
                details=read_error or integrity_res.error_message or "Violação de integridade detectada.",
            )

        # Clean and intact
        status = FileScanStatus.OK_ENCRYPTED if is_encrypted else FileScanStatus.OK
        return FileScanResult(
            path=canonical_path,
            status=status,
            expected_hash=integrity_res.expected_hash,
            actual_hash=integrity_res.actual_hash,
            hmac_valid=integrity_res.hmac_valid,
            is_encrypted=is_encrypted,
            size_bytes=inode.file_size,
            details="Arquivo íntegro e autêntico.",
        )

    def scan_path(
        self,
        path: str = "/",
        context: Optional[ExecutionContext] = None,
    ) -> AntivirusScanReport:
        """Recursively scan filesystem starting from given path."""
        start_time = time.time()
        canonical_target = self.fs_service.vfs.normalize_path(path)
        report = AntivirusScanReport(target_path=canonical_target, start_time=start_time)

        target_node = self.fs_service.vfs.get_node(canonical_target)
        if target_node is None:
            raise FileNotFoundException(f"Caminho '{path}' não encontrado no sistema de arquivos.")

        if target_node.node_type == NodeType.FILE:
            res = self.scan_file(canonical_target, context=context)
            report.add_result(res)
            report.end_time = time.time()
            return report

        # Directory traversal
        def _walk_dir(dir_node: Any):
            dir_path = dir_node.get_path()
            # If context provided, check directory traversal ('x')
            if context is not None and self.auth_port is not None:
                can_traverse = True
                dir_inode = self.fs_service.inode_table.get(dir_node.inode_id)
                try:
                    can_traverse = self.auth_port.check_execute(context, dir_path, dir_inode)
                except TypeError:
                    can_traverse = self.auth_port.check_execute(context, dir_path)
                except Exception:
                    can_traverse = False

                if not can_traverse:
                    # Mark all files inside as inaccessible
                    for child in dir_node.list_children():
                        if child.node_type == NodeType.FILE:
                            report.add_result(
                                FileScanResult(
                                    path=child.get_path(),
                                    status=FileScanStatus.INACCESSIBLE,
                                    details="Diretório pai sem permissão de execução/travessia ('x').",
                                )
                            )
                    return

            for child in dir_node.list_children():
                if child.node_type == NodeType.FILE:
                    res = self.scan_file(child.get_path(), context=context)
                    report.add_result(res)
                elif child.node_type == NodeType.DIRECTORY:
                    _walk_dir(child)

        _walk_dir(target_node)
        report.end_time = time.time()
        return report

    def format_report(self, report: Optional[AntivirusScanReport] = None) -> str:
        """Format an AntivirusScanReport as string."""
        if report is None:
            report = self.scan_path("/")
        return report.format_report()


__all__ = [
    "SIMULATED_MALWARE_SIGNATURES",
    "DEFAULT_MALWARE_SIGNATURES",
    "FileScanStatus",
    "ScanStatus",
    "STATUS_DISPLAY_LABELS",
    "IntegrityRecord",
    "IntegrityCheckResult",
    "FileScanResult",
    "AntivirusScanReport",
    "BaselineCatalog",
    "IntegrityChecker",
    "AntivirusScanner",
]
