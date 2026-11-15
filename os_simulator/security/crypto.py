"""Cryptographic subsystem for OS Simulator (AES-256-GCM at-rest encryption).

Provides authenticated encryption, structured payload packaging, key derivation
via PBKDF2/HKDF, transparent block-level device encryption (CryptoBlockDeviceAdapter),
and file-level encryption helpers.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from os_simulator.core.exceptions import (
    AuthenticationFailedException,
    CryptoKeyException,
    DecryptionFailedException,
    FileNotFoundException,
    InvalidTagException,
    SecurityException,
    StorageException,
)
from os_simulator.core.ports import BlockDevicePort

# Cryptographic Constants
AES_KEY_SIZE_BYTES = 32         # 256 bits
GCM_NONCE_SIZE_BYTES = 12       # 96 bits
GCM_TAG_SIZE_BYTES = 16         # 128 bits
MIN_ENCRYPTED_PAYLOAD_SIZE = GCM_NONCE_SIZE_BYTES + GCM_TAG_SIZE_BYTES  # 28 bytes
DEFAULT_PBKDF2_ITERATIONS = 600_000
DEFAULT_KDF_SALT = b"os_simulator_crypto_v1_salt"


@dataclass
class EncryptedPayload:
    """Structured container for AES-256-GCM authenticated ciphertext.

    Attributes:
        nonce: 12-byte initialization vector (never reused for same key).
        tag: 16-byte AEAD authentication tag verifying integrity/authenticity.
        ciphertext: Encrypted binary payload.
        key_id: Identifier of the derived key used.
    """

    nonce: bytes
    tag: bytes
    ciphertext: bytes
    key_id: str = "default"

    def __post_init__(self) -> None:
        if len(self.nonce) != GCM_NONCE_SIZE_BYTES:
            raise CryptoKeyException(
                f"Nonce deve ter exatamente {GCM_NONCE_SIZE_BYTES} bytes, recebido {len(self.nonce)}."
            )
        if len(self.tag) != GCM_TAG_SIZE_BYTES:
            raise CryptoKeyException(
                f"Tag de autenticação deve ter exatamente {GCM_TAG_SIZE_BYTES} bytes, recebido {len(self.tag)}."
            )

    def pack(self, tag_first: bool = False) -> bytes:
        """Serialize payload to raw bytes for storage.

        Args:
            tag_first: If True, uses layout [Nonce (12B)] + [Tag (16B)] + [Ciphertext].
                       If False, uses standard layout [Nonce (12B)] + [Ciphertext] + [Tag (16B)].
        """
        if tag_first:
            return self.nonce + self.tag + self.ciphertext
        return self.nonce + self.ciphertext + self.tag

    def to_bytes(self, tag_first: bool = False) -> bytes:
        """Alias for pack()."""
        return self.pack(tag_first=tag_first)

    @classmethod
    def unpack(
        cls,
        raw: bytes | bytearray,
        key_id: str = "default",
        tag_first: Optional[bool] = None,
    ) -> EncryptedPayload:
        """Deserialize raw binary payload into EncryptedPayload object.

        Args:
            raw: Raw binary data containing nonce, tag, and ciphertext.
            key_id: Optional key identifier.
            tag_first: Explicit ordering flag. If None, default layout is used
                       ([Nonce 12B] + [Ciphertext] + [Tag 16B]).
        """
        data = bytes(raw)
        if len(data) < MIN_ENCRYPTED_PAYLOAD_SIZE:
            raise DecryptionFailedException(
                f"Carga cifrada corrompida ou truncada: tamanho ({len(data)} B) "
                f"inferior ao mínimo exigido ({MIN_ENCRYPTED_PAYLOAD_SIZE} B)."
            )

        nonce = data[:GCM_NONCE_SIZE_BYTES]
        if len(data) == MIN_ENCRYPTED_PAYLOAD_SIZE:
            # Empty ciphertext
            tag = data[GCM_NONCE_SIZE_BYTES:MIN_ENCRYPTED_PAYLOAD_SIZE]
            ciphertext = b""
            return cls(nonce=nonce, tag=tag, ciphertext=ciphertext, key_id=key_id)

        if tag_first is True:
            tag = data[GCM_NONCE_SIZE_BYTES : GCM_NONCE_SIZE_BYTES + GCM_TAG_SIZE_BYTES]
            ciphertext = data[GCM_NONCE_SIZE_BYTES + GCM_TAG_SIZE_BYTES :]
        else:
            # Standard wire format
            ciphertext = data[GCM_NONCE_SIZE_BYTES : -GCM_TAG_SIZE_BYTES]
            tag = data[-GCM_TAG_SIZE_BYTES:]

        return cls(nonce=nonce, tag=tag, ciphertext=ciphertext, key_id=key_id)


def pack_payload(
    nonce: bytes,
    ciphertext: bytes,
    tag: Optional[bytes] = None,
    tag_first: bool = False,
) -> bytes:
    """Helper method to serialize nonce, ciphertext, and tag into a single byte stream.

    If tag is omitted, ciphertext is assumed to already have tag appended
    (as returned by AESGCM.encrypt).
    """
    if tag is None:
        # ciphertext has tag appended at end
        if len(ciphertext) < GCM_TAG_SIZE_BYTES:
            raise DecryptionFailedException("Ciphertext truncado, menor que o tamanho da tag.")
        actual_ct = ciphertext[:-GCM_TAG_SIZE_BYTES]
        actual_tag = ciphertext[-GCM_TAG_SIZE_BYTES:]
    else:
        # Check if caller passed tag in 2nd position and ciphertext in 3rd position
        if len(ciphertext) == GCM_TAG_SIZE_BYTES and len(tag) != GCM_TAG_SIZE_BYTES:
            actual_tag = ciphertext
            actual_ct = tag
        else:
            actual_ct = ciphertext
            actual_tag = tag

    payload = EncryptedPayload(nonce=nonce, tag=actual_tag, ciphertext=actual_ct)
    return payload.pack(tag_first=tag_first)


def unpack_payload(
    raw: bytes | bytearray,
    tag_first: Optional[bool] = None,
) -> EncryptedPayload:
    """Helper method to deserialize raw bytes into EncryptedPayload."""
    return EncryptedPayload.unpack(raw, tag_first=tag_first)


# -------------------------------------------------------------------------
# Key Derivation and Key Management
# -------------------------------------------------------------------------

def validate_key(key: bytes | bytearray) -> None:
    """Verify that key is exactly 256 bits (32 bytes)."""
    if not isinstance(key, (bytes, bytearray)):
        raise CryptoKeyException("Chave criptográfica deve ser do tipo bytes ou bytearray.")
    if len(key) != AES_KEY_SIZE_BYTES:
        raise CryptoKeyException(
            f"Chave AES-256 deve possuir exatamente {AES_KEY_SIZE_BYTES} bytes (256 bits), "
            f"fornecido {len(key)} bytes."
        )


def generate_key() -> bytes:
    """Generate a cryptographically secure 256-bit random key."""
    return secrets.token_bytes(AES_KEY_SIZE_BYTES)


def derive_key_from_passphrase(
    passphrase: str | bytes,
    salt: Optional[bytes] = None,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
) -> bytes:
    """Derive 256-bit AES key from a passphrase via PBKDF2-HMAC-SHA256.

    Args:
        passphrase: Secret passphrase or password string/bytes.
        salt: Cryptographic salt (default: DEFAULT_KDF_SALT).
        iterations: Number of PBKDF2 rounds (default: 600,000).

    Returns:
        32-byte derived encryption key.
    """
    if isinstance(passphrase, str):
        passphrase_bytes = passphrase.encode("utf-8")
    else:
        passphrase_bytes = bytes(passphrase)

    actual_salt = salt if salt is not None else DEFAULT_KDF_SALT
    return hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=passphrase_bytes,
        salt=actual_salt,
        iterations=iterations,
        dklen=AES_KEY_SIZE_BYTES,
    )


def derive_file_encryption_key(
    master_key: bytes,
    context_info: str = "file-encryption",
    salt: Optional[bytes] = None,
) -> bytes:
    """Derive a specialized file encryption key from a master key using HKDF-SHA256.

    Ensures domain separation between login credentials, storage root keys, and files.

    Args:
        master_key: Root or master cryptographic key (32 bytes).
        context_info: Contextual label isolating this key purpose.
        salt: Optional salt for HKDF.

    Returns:
        32-byte derived sub-key.
    """
    validate_key(master_key)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=AES_KEY_SIZE_BYTES,
        salt=salt,
        info=context_info.encode("utf-8"),
    )
    return hkdf.derive(master_key)


class CryptoKeyManager:
    """In-memory key management registry for master and derived keys."""

    def __init__(self, master_key: Optional[bytes] = None):
        if master_key is not None:
            validate_key(master_key)
            self._master_key = master_key
        else:
            self._master_key = generate_key()

        self._keys: Dict[str, bytes] = {
            "master": self._master_key,
        }

    @property
    def master_key(self) -> bytes:
        return self._master_key

    def set_key(self, key_id: str, key_bytes: bytes) -> None:
        """Register a key under key_id."""
        validate_key(key_bytes)
        self._keys[key_id] = key_bytes

    def get_key(self, key_id: str = "master") -> bytes:
        """Retrieve key by ID."""
        if key_id not in self._keys:
            raise CryptoKeyException(f"Chave criptográfica '{key_id}' não encontrada.")
        return self._keys[key_id]

    def derive_and_register(self, key_id: str, context_info: str) -> bytes:
        """Derive a subkey using master key and register it under key_id."""
        subkey = derive_file_encryption_key(self._master_key, context_info=context_info)
        self._keys[key_id] = subkey
        return subkey


# -------------------------------------------------------------------------
# Core Crypto Engine (AES-256-GCM)
# -------------------------------------------------------------------------

class CryptoEngine:
    """Core cryptographic engine for AES-256-GCM authenticated encryption and decryption."""

    @staticmethod
    def _normalize_key(key: bytes | str) -> bytes:
        """Convert string passphrase to 32-byte key or validate existing 32-byte key."""
        if isinstance(key, str):
            return derive_key_from_passphrase(key)
        validate_key(key)
        return bytes(key)

    @classmethod
    def encrypt(
        cls,
        data: bytes | bytearray | str,
        key: bytes | str,
        associated_data: Optional[bytes] = None,
        key_id: str = "default",
        tag_first: bool = False,
    ) -> EncryptedPayload:
        """Encrypt plaintext using AES-256-GCM with fresh 12-byte random nonce.

        Args:
            data: Binary payload or string to encrypt.
            key: 32-byte key or passphrase string.
            associated_data: Optional AEAD associated data for integrity binding.
            key_id: Optional key identifier metadata.
            tag_first: Whether to pack with tag before ciphertext.

        Returns:
            EncryptedPayload with nonce, tag, and ciphertext.
        """
        raw_key = cls._normalize_key(key)
        plaintext = data.encode("utf-8") if isinstance(data, str) else bytes(data)

        # Generate unique 12-byte nonce (never reused)
        nonce = secrets.token_bytes(GCM_NONCE_SIZE_BYTES)
        aesgcm = AESGCM(raw_key)

        # AESGCM encrypt returns ciphertext with 16-byte authentication tag appended
        ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext, associated_data)
        ciphertext = ciphertext_and_tag[:-GCM_TAG_SIZE_BYTES]
        tag = ciphertext_and_tag[-GCM_TAG_SIZE_BYTES:]

        return EncryptedPayload(nonce=nonce, tag=tag, ciphertext=ciphertext, key_id=key_id)

    @classmethod
    def decrypt(
        cls,
        payload: EncryptedPayload | bytes | bytearray,
        key: bytes | str,
        associated_data: Optional[bytes] = None,
    ) -> bytes:
        """Decrypt AES-256-GCM ciphertext and verify authentic tag.

        Raises:
            InvalidTagException: If authentication tag check fails (tampered data or wrong key).
            DecryptionFailedException: If payload is malformed or corrupted.
            CryptoKeyException: If key is invalid.

        Returns:
            Decrypted plaintext bytes.
        """
        raw_key = cls._normalize_key(key)
        aesgcm = AESGCM(raw_key)

        if isinstance(payload, EncryptedPayload):
            try:
                return aesgcm.decrypt(payload.nonce, payload.ciphertext + payload.tag, associated_data)
            except InvalidTag as e:
                raise InvalidTagException(
                    "Falha na autenticação da tag AES-GCM: dados adulterados ou chave incorreta."
                ) from e

        # Handle raw serialized bytes
        raw_bytes = bytes(payload)
        if len(raw_bytes) < MIN_ENCRYPTED_PAYLOAD_SIZE:
            raise DecryptionFailedException(
                f"Carga cifrada corrompida: tamanho {len(raw_bytes)} B inferior ao mínimo {MIN_ENCRYPTED_PAYLOAD_SIZE} B."
            )

        # Attempt standard layout ([Nonce 12B] + [Ciphertext] + [Tag 16B])
        p1 = EncryptedPayload.unpack(raw_bytes, tag_first=False)
        try:
            return aesgcm.decrypt(p1.nonce, p1.ciphertext + p1.tag, associated_data)
        except InvalidTag:
            # Fallback to alternative layout ([Nonce 12B] + [Tag 16B] + [Ciphertext]) if not empty
            if len(raw_bytes) > MIN_ENCRYPTED_PAYLOAD_SIZE:
                p2 = EncryptedPayload.unpack(raw_bytes, tag_first=True)
                try:
                    return aesgcm.decrypt(p2.nonce, p2.ciphertext + p2.tag, associated_data)
                except InvalidTag:
                    pass

            raise InvalidTagException(
                "Falha na autenticação da tag AES-GCM: dados adulterados ou chave incorreta."
            )


# -------------------------------------------------------------------------
# Transparent Block Device Adapter (CryptoBlockDeviceAdapter)
# -------------------------------------------------------------------------

class CryptoBlockDeviceAdapter(BlockDevicePort):
    """Transparent authenticated encryption wrapper for BlockDevicePort.

    Wraps any underlying BlockDevicePort (e.g. InMemoryBlockDevice, IOBlockDeviceAdapter,
    or RAIDArray). Blocks written to disk are genuine AES-256-GCM authenticated ciphertexts;
    blocks read are automatically verified and decrypted.
    """

    BLOCK_HEADER_SIZE = 4  # 4-byte big-endian payload length prefix

    def __init__(
        self,
        device: BlockDevicePort,
        key: Optional[bytes | str] = None,
        key_id: str = "storage_master",
    ):
        self.device = device
        self.key_id = key_id
        if key is None:
            self._key = generate_key()
        elif isinstance(key, str):
            self._key = derive_key_from_passphrase(key)
        else:
            validate_key(key)
            self._key = bytes(key)

        self._cipher = AESGCM(self._key)

    @property
    def key(self) -> bytes:
        return self._key

    def get_physical_device(self) -> BlockDevicePort:
        """Access underlying physical/storage block device."""
        return self.device

    def get_physical_block_size(self) -> int:
        """Physical block size of underlying device."""
        return self.device.get_block_size()

    def get_block_size(self) -> int:
        """Usable data size per block after reserving header, nonce, and auth tag."""
        raw_size = self.device.get_block_size()
        return max(0, raw_size - (MIN_ENCRYPTED_PAYLOAD_SIZE + self.BLOCK_HEADER_SIZE))

    def write_block(self, block_id: int, data: bytearray | bytes) -> None:
        """Encrypt plaintext block and write authentic ciphertext to underlying storage."""
        raw_data = bytes(data)
        usable_size = self.get_block_size()
        if len(raw_data) > usable_size:
            raise StorageException(
                f"Tamanho dos dados ({len(raw_data)} B) excede o limite útil do bloco cifrado ({usable_size} B)."
            )

        payload = CryptoEngine.encrypt(raw_data, self._key, key_id=self.key_id)
        packed = payload.pack()
        header = struct.pack(">I", len(packed))
        full_payload = header + packed
        self.device.write_block(block_id, full_payload)

    def read_block(self, block_id: int) -> bytearray:
        """Read ciphertext from underlying storage, verify AEAD tag, and return plaintext."""
        raw = self.device.read_block(block_id)
        if not raw or (isinstance(raw, (bytes, bytearray)) and all(b == 0 for b in raw)):
            return bytearray()

        try:
            # Check for 4-byte length prefix header
            if len(raw) >= self.BLOCK_HEADER_SIZE + MIN_ENCRYPTED_PAYLOAD_SIZE:
                payload_len = struct.unpack(">I", raw[:self.BLOCK_HEADER_SIZE])[0]
                if MIN_ENCRYPTED_PAYLOAD_SIZE <= payload_len <= len(raw) - self.BLOCK_HEADER_SIZE:
                    packed_payload = raw[self.BLOCK_HEADER_SIZE : self.BLOCK_HEADER_SIZE + payload_len]
                    plaintext = CryptoEngine.decrypt(packed_payload, self._key)
                    return bytearray(plaintext)

            # Fallback to direct raw payload without header
            plaintext = CryptoEngine.decrypt(raw, self._key)
            return bytearray(plaintext)
        except (InvalidTagException, DecryptionFailedException, Exception) as e:
            raise InvalidTagException(
                f"Falha na integridade do bloco cifrado {block_id}: dados adulterados ou chave inválida."
            ) from e

    # Delegation of block allocation and capacity methods to underlying device
    def allocate_block(self) -> int:
        return self.device.allocate_block()

    def allocate_blocks(self, count: int) -> List[int]:
        return self.device.allocate_blocks(count)

    def allocate_specific_blocks(self, block_ids: List[int]) -> List[int]:
        return self.device.allocate_specific_blocks(block_ids)

    def free_block(self, block_id: int) -> None:
        self.device.free_block(block_id)

    def free_blocks(self, block_ids: List[int]) -> None:
        self.device.free_blocks(block_ids)

    def get_capacity(self) -> int:
        return self.device.get_capacity()

    def get_free_count(self) -> int:
        return self.device.get_free_count()

    def get_used_count(self) -> int:
        return self.device.get_used_count()

    def is_available(self, block_id: int) -> bool:
        return self.device.is_available(block_id)

    def is_block_free(self, block_id: int) -> bool:
        return self.device.is_block_free(block_id)


# Alias as requested in brief:
EncryptedBlockDevicePort = CryptoBlockDeviceAdapter


# -------------------------------------------------------------------------
# File-Level Encryption Helpers
# -------------------------------------------------------------------------

def is_file_encrypted(fs: Any, path: str, cwd: str = "/") -> bool:
    """Check whether a file on the filesystem is marked as encrypted."""
    node = fs.vfs.get_file(path, cwd)
    if node is None:
        raise FileNotFoundException(f"Arquivo '{path}' não encontrado.")
    inode = fs.inode_table[node.inode_id]
    return getattr(inode, "is_encrypted", False)


def encrypt_file(
    fs: Any,
    path: str,
    key: bytes | str,
    cwd: str = "/",
) -> Dict[str, Any]:
    """Encrypt an existing file in-place on the filesystem.

    Updates the physical storage blocks with genuine AES-256-GCM ciphertext,
    sets inode.is_encrypted = True, and preserves the inode allocation.

    Args:
        fs: FileSystemService instance.
        path: Path to target file.
        key: Encryption key or passphrase.
        cwd: Current working directory for resolution.

    Returns:
        Dictionary with status, encrypted size, and block mappings.
    """
    node = fs.vfs.get_file(path, cwd)
    if node is None:
        raise FileNotFoundException(f"Arquivo '{path}' não encontrado.")

    inode = fs.inode_table[node.inode_id]
    if getattr(inode, "is_encrypted", False):
        raise SecurityException(f"Arquivo '{path}' já está criptografado.")

    # Read current plaintext payload
    from os_simulator.filesystem.allocation import AllocationStrategyFactory
    strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)

    if inode.file_size > 0:
        plaintext = strategy_handler.read_data(fs.device, inode)
    else:
        plaintext = b""

    # Encrypt plaintext with AES-256-GCM
    payload = CryptoEngine.encrypt(plaintext, key)
    ciphertext_packed = payload.pack()

    # Write ciphertext directly into the file's allocated storage blocks
    strategy_handler.write_data(fs.device, inode, ciphertext_packed)
    inode.is_encrypted = True

    return {
        "path": node.get_path(),
        "inode_id": inode.inode_id,
        "is_encrypted": True,
        "original_size": len(plaintext),
        "encrypted_size": len(ciphertext_packed),
        "allocated_blocks": list(inode.allocated_blocks),
    }


def decrypt_file(
    fs: Any,
    path: str,
    key: bytes | str,
    in_place: bool = True,
    cwd: str = "/",
) -> bytes:
    """Decrypt an encrypted file on the filesystem, verifying AEAD authentication.

    Args:
        fs: FileSystemService instance.
        path: Path to target file.
        key: Decryption key or passphrase.
        in_place: If True, writes decrypted plaintext back to disk and clears
                  inode.is_encrypted flag. If False, disk remains encrypted.
        cwd: Current working directory.

    Raises:
        InvalidTagException: If ciphertext is tampered or wrong key is supplied.
        SecurityException: If file is not encrypted.

    Returns:
        Decrypted plaintext bytes.
    """
    node = fs.vfs.get_file(path, cwd)
    if node is None:
        raise FileNotFoundException(f"Arquivo '{path}' não encontrado.")

    inode = fs.inode_table[node.inode_id]
    if not getattr(inode, "is_encrypted", False):
        raise SecurityException(f"Arquivo '{path}' não está criptografado.")

    from os_simulator.filesystem.allocation import AllocationStrategyFactory
    strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)

    # Read raw ciphertext from storage blocks
    raw_ciphertext = strategy_handler.read_data(fs.device, inode)

    # Decrypt and verify tag (raises InvalidTagException if tampered or wrong key)
    plaintext = CryptoEngine.decrypt(raw_ciphertext, key)

    if in_place:
        strategy_handler.write_data(fs.device, inode, plaintext)
        inode.is_encrypted = False

    return plaintext


def read_encrypted_file(
    fs: Any,
    path: str,
    key: bytes | str,
    cwd: str = "/",
) -> str:
    """Read and decrypt an encrypted file in-memory without altering disk state.

    Returns:
        Decoded UTF-8 string content.
    """
    plaintext_bytes = decrypt_file(fs, path, key, in_place=False, cwd=cwd)
    return plaintext_bytes.decode("utf-8", errors="replace")


def write_encrypted_file(
    fs: Any,
    path: str,
    content: str | bytes | bytearray,
    key: bytes | str,
    cwd: str = "/",
) -> Dict[str, Any]:
    """Create or overwrite a file directly with authenticated encryption.

    Sets inode.is_encrypted = True immediately upon write.
    """
    raw_data = content.encode("utf-8") if isinstance(content, str) else bytes(content)

    from os_simulator.filesystem.node import FileNode
    node = fs.vfs.get_node(path, cwd)
    if node is None:
        file_node = fs.create_file(path, size_bytes=0, cwd=cwd)
    elif isinstance(node, FileNode):
        file_node = node
    else:
        raise SecurityException(f"'{path}' é um diretório e não pode ser gravado.")

    inode = fs.inode_table[file_node.inode_id]
    from os_simulator.filesystem.allocation import AllocationStrategyFactory
    strategy_handler = AllocationStrategyFactory.get_strategy(inode.allocation_strategy)

    payload = CryptoEngine.encrypt(raw_data, key)
    ciphertext_packed = payload.pack()

    strategy_handler.write_data(fs.device, inode, ciphertext_packed)
    inode.is_encrypted = True

    return {
        "path": file_node.get_path(),
        "inode_id": inode.inode_id,
        "is_encrypted": True,
        "real_size": len(raw_data),
        "encrypted_size": len(ciphertext_packed),
        "allocated_blocks": list(inode.allocated_blocks),
    }
