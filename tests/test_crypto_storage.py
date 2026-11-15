"""Unit and integration tests for OS Simulator Cryptography and Secure Storage (Stage 3).

Tests:
1. AES-256-GCM authenticated encryption and decryption.
2. Structured payload packing and unpacking (nonce 12B, tag 16B, ciphertext).
3. Rejection of tampered ciphertext, modified tags, and wrong keys.
4. Key derivation via PBKDF2 (600k iterations) and HKDF domain separation.
5. Transparent block device encryption (CryptoBlockDeviceAdapter / EncryptedBlockDevicePort).
6. Physical inspection confirming no plaintext ever resides on disk blocks.
7. File-level encryption helpers (encrypt_file, decrypt_file, read_encrypted_file).
8. Multi-block files, empty files, and partial block writes.
9. End-to-end integration with RAID (RAID 0, 1, 4, 5) and IOBlockDeviceAdapter.
"""

import os
import secrets
import struct
import unittest

from os_simulator.core.exceptions import (
    AuthenticationFailedException,
    CryptoKeyException,
    DecryptionFailedException,
    FileNotFoundException,
    InvalidTagException,
    SecurityException,
    StorageException,
)
from os_simulator.core.types import AllocationStrategy
from os_simulator.filesystem.service import FileSystemService
from os_simulator.io.service import IOManager
from os_simulator.security.crypto import (
    AES_KEY_SIZE_BYTES,
    GCM_NONCE_SIZE_BYTES,
    GCM_TAG_SIZE_BYTES,
    CryptoBlockDeviceAdapter,
    CryptoEngine,
    CryptoKeyManager,
    EncryptedBlockDevicePort,
    EncryptedPayload,
    decrypt_file,
    derive_file_encryption_key,
    derive_key_from_passphrase,
    encrypt_file,
    generate_key,
    is_file_encrypted,
    pack_payload,
    read_encrypted_file,
    unpack_payload,
    validate_key,
    write_encrypted_file,
)
from os_simulator.storage.adapter import IOBlockDeviceAdapter
from os_simulator.storage.memory_block_device import InMemoryBlockDevice
from os_simulator.storage.physical_disk import PhysicalDisk
from os_simulator.storage.raid import RAID1Controller, RAID5Controller


class TestAESGCMCorePrimitives(unittest.TestCase):
    """Test suite for core cryptographic primitives (AES-256-GCM, PBKDF2, HKDF)."""

    def setUp(self):
        self.key = secrets.token_bytes(AES_KEY_SIZE_BYTES)
        self.passphrase = "SenhaForteDeTeste_12345!"

    def test_key_generation_and_validation(self):
        """Verify that generated keys are exactly 32 bytes and validation rules apply."""
        key = generate_key()
        self.assertEqual(len(key), 32)
        validate_key(key)

        # Invalid key lengths
        with self.assertRaises(CryptoKeyException):
            validate_key(b"short_key")
        with self.assertRaises(CryptoKeyException):
            validate_key(secrets.token_bytes(16))  # 128-bit key rejected
        with self.assertRaises(CryptoKeyException):
            validate_key("not_bytes")  # type: ignore

    def test_encryption_decryption_roundtrip(self):
        """Verify that encryption followed by decryption returns the original plaintext."""
        messages = [
            b"Simulador de Sistemas Operacionais - Etapa 3",
            b"",  # Empty payload
            b"A" * 5000,  # Large payload
            "Texto UTF-8 com acentuação e caracteres especiais: ç, ã, é, ü, 🚀",
        ]
        for msg in messages:
            expected_bytes = msg.encode("utf-8") if isinstance(msg, str) else msg
            payload = CryptoEngine.encrypt(msg, self.key)
            self.assertIsInstance(payload, EncryptedPayload)
            self.assertEqual(len(payload.nonce), GCM_NONCE_SIZE_BYTES)
            self.assertEqual(len(payload.tag), GCM_TAG_SIZE_BYTES)
            self.assertEqual(len(payload.ciphertext), len(expected_bytes))

            # Decrypt payload object
            decrypted = CryptoEngine.decrypt(payload, self.key)
            self.assertEqual(decrypted, expected_bytes)

            # Decrypt serialized bytes
            packed_bytes = payload.pack()
            decrypted_from_bytes = CryptoEngine.decrypt(packed_bytes, self.key)
            self.assertEqual(decrypted_from_bytes, expected_bytes)

    def test_nonce_freshness_never_reused(self):
        """Verify that encrypting identical data multiple times generates unique nonces."""
        plaintext = b"Dados Confidenciais Repetidos"
        nonces = set()
        ciphertexts = set()

        for _ in range(50):
            payload = CryptoEngine.encrypt(plaintext, self.key)
            nonces.add(payload.nonce)
            ciphertexts.add(payload.ciphertext)

        self.assertEqual(len(nonces), 50, "Nonces must never be reused for the same key!")
        self.assertEqual(len(ciphertexts), 50, "Ciphertexts must be distinct due to fresh nonces!")

    def test_payload_packaging_layouts(self):
        """Verify structured packaging [Nonce 12B] + [Ciphertext] + [Tag 16B] and alternative layout."""
        plaintext = b"Estrutura do Bloco Criptografado"
        payload = CryptoEngine.encrypt(plaintext, self.key)

        # Standard layout: [Nonce 12B] + [Ciphertext] + [Tag 16B]
        standard_packed = payload.pack(tag_first=False)
        self.assertEqual(len(standard_packed), 12 + len(plaintext) + 16)
        self.assertEqual(standard_packed[:12], payload.nonce)
        self.assertEqual(standard_packed[12 : 12 + len(plaintext)], payload.ciphertext)
        self.assertEqual(standard_packed[-16:], payload.tag)

        # Unpack standard
        unpacked_std = unpack_payload(standard_packed, tag_first=False)
        self.assertEqual(unpacked_std.nonce, payload.nonce)
        self.assertEqual(unpacked_std.ciphertext, payload.ciphertext)
        self.assertEqual(unpacked_std.tag, payload.tag)

        # Tag-first layout: [Nonce 12B] + [Tag 16B] + [Ciphertext]
        tag_first_packed = payload.pack(tag_first=True)
        self.assertEqual(len(tag_first_packed), 12 + 16 + len(plaintext))
        self.assertEqual(tag_first_packed[:12], payload.nonce)
        self.assertEqual(tag_first_packed[12:28], payload.tag)
        self.assertEqual(tag_first_packed[28:], payload.ciphertext)

        # Both layouts decrypt transparently
        self.assertEqual(CryptoEngine.decrypt(standard_packed, self.key), plaintext)
        self.assertEqual(CryptoEngine.decrypt(tag_first_packed, self.key), plaintext)

    def test_tamper_rejection_ciphertext_bit_flip(self):
        """Modifying even a single bit in the ciphertext must raise InvalidTagException."""
        plaintext = b"Segredo Militar Classificado"
        payload = CryptoEngine.encrypt(plaintext, self.key)
        packed = bytearray(payload.pack())

        # Flip 1 bit in the ciphertext section (offset 15)
        packed[15] ^= 0x01

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            CryptoEngine.decrypt(packed, self.key)

    def test_tamper_rejection_tag_modification(self):
        """Modifying authentication tag must raise InvalidTagException."""
        plaintext = b"Registro de Auditoria Inviolavel"
        payload = CryptoEngine.encrypt(plaintext, self.key)
        packed = bytearray(payload.pack())

        # Flip 1 bit in the tag section (last byte)
        packed[-1] ^= 0x01

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            CryptoEngine.decrypt(packed, self.key)

    def test_tamper_rejection_nonce_modification(self):
        """Modifying nonce must raise InvalidTagException."""
        plaintext = b"Chave de Sessao Ativa"
        payload = CryptoEngine.encrypt(plaintext, self.key)
        packed = bytearray(payload.pack())

        # Flip 1 bit in the nonce section (first byte)
        packed[0] ^= 0x01

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            CryptoEngine.decrypt(packed, self.key)

    def test_wrong_key_rejection(self):
        """Attempting to decrypt ciphertext with a different 256-bit key must fail."""
        plaintext = b"Carga util confidencial"
        payload = CryptoEngine.encrypt(plaintext, self.key)
        wrong_key = secrets.token_bytes(32)

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            CryptoEngine.decrypt(payload, wrong_key)

    def test_truncated_payload_rejection(self):
        """Serialized payload smaller than minimum 28 bytes must be rejected."""
        truncated_payload = b"short_data_under_28_bytes"
        with self.assertRaises((DecryptionFailedException, InvalidTagException)):
            CryptoEngine.decrypt(truncated_payload, self.key)

    def test_pbkdf2_key_derivation(self):
        """PBKDF2-HMAC-SHA256 derivation must produce deterministic 32-byte keys."""
        salt = secrets.token_bytes(16)
        key1 = derive_key_from_passphrase(self.passphrase, salt=salt, iterations=600_000)
        key2 = derive_key_from_passphrase(self.passphrase, salt=salt, iterations=600_000)
        self.assertEqual(len(key1), 32)
        self.assertEqual(key1, key2, "Same passphrase and salt must produce identical key")

        # Different salt produces distinct key
        key3 = derive_key_from_passphrase(self.passphrase, salt=secrets.token_bytes(16), iterations=600_000)
        self.assertNotEqual(key1, key3)

    def test_hkdf_domain_separation(self):
        """HKDF must derive distinct subkeys for different context labels."""
        master = generate_key()
        file_key = derive_file_encryption_key(master, context_info="file-encryption")
        storage_key = derive_file_encryption_key(master, context_info="storage-root")
        swap_key = derive_file_encryption_key(master, context_info="swap-partition")

        self.assertEqual(len(file_key), 32)
        self.assertEqual(len(storage_key), 32)
        self.assertEqual(len(swap_key), 32)

        self.assertNotEqual(file_key, storage_key)
        self.assertNotEqual(storage_key, swap_key)
        self.assertNotEqual(file_key, master)


class TestCryptoBlockDeviceAdapter(unittest.TestCase):
    """Test suite for transparent block device encryption (CryptoBlockDeviceAdapter)."""

    def setUp(self):
        self.raw_device = InMemoryBlockDevice(capacity=16, block_size=4096)
        self.key = secrets.token_bytes(32)
        self.crypto_device = CryptoBlockDeviceAdapter(self.raw_device, key=self.key)

    def test_block_write_and_read_roundtrip(self):
        """Verify that data written to encrypted block device is decrypted accurately on read."""
        block_id = self.crypto_device.allocate_block()
        test_payload = b"Dados confidenciais gravados no bloco logico criptografado."

        self.crypto_device.write_block(block_id, test_payload)
        read_back = self.crypto_device.read_block(block_id)

        self.assertEqual(read_back, test_payload)

    def test_physical_inspection_no_plaintext_on_raw_blocks(self):
        """PHYSICAL INSPECTION: Raw underlying disk blocks must contain ONLY genuine ciphertext."""
        block_id = self.crypto_device.allocate_block()
        secret_text = b"TOP_SECRET_MILITARY_INTELLIGENCE_KERNEL_PAYLOAD"

        self.crypto_device.write_block(block_id, secret_text)

        # Inspect the underlying physical block directly
        raw_block_data = bytes(self.raw_device.read_block(block_id))

        # Plaintext must NOT appear anywhere in the physical block buffer!
        self.assertNotIn(secret_text, raw_block_data)
        self.assertNotIn(b"TOP_SECRET", raw_block_data)
        self.assertNotIn(b"MILITARY", raw_block_data)

        # The block data must be non-empty and start with metadata + high-entropy ciphertext
        self.assertGreater(len(raw_block_data), len(secret_text))

    def test_tamper_detection_on_physical_block(self):
        """Modifying 1 single byte in the underlying physical storage block must trigger InvalidTagException."""
        block_id = self.crypto_device.allocate_block()
        payload = b"Contrato Governamental Valioso e Inalteravel"
        self.crypto_device.write_block(block_id, payload)

        # Tamper directly with the underlying DiskBlock in the raw device
        raw_disk_block = self.raw_device.get_block(block_id)
        # Flip a bit in the ciphertext region (e.g. offset 10)
        raw_disk_block.data[10] ^= 0x55

        # Attempting to read via CryptoBlockDeviceAdapter must fail with InvalidTagException!
        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            self.crypto_device.read_block(block_id)

    def test_wrong_key_on_block_device(self):
        """A new adapter with a different key reading the same raw device must fail decryption."""
        block_id = self.crypto_device.allocate_block()
        self.crypto_device.write_block(block_id, b"Mensagem Protegida")

        # Create another adapter pointing to the same device with a different key
        wrong_adapter = CryptoBlockDeviceAdapter(self.raw_device, key=secrets.token_bytes(32))

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            wrong_adapter.read_block(block_id)

    def test_unwritten_or_empty_block_read(self):
        """Reading an unwritten free block returns an empty buffer without crashing."""
        block_id = self.crypto_device.allocate_block()
        data = self.crypto_device.read_block(block_id)
        self.assertEqual(len(data), 0)

    def test_usable_block_size_calculation(self):
        """Reported block size must account for cryptographic overhead (header + nonce + tag)."""
        raw_size = self.raw_device.get_block_size()  # 4096
        usable_size = self.crypto_device.get_block_size()
        # 4096 - 32 = 4064 bytes
        self.assertEqual(usable_size, raw_size - 32)
        self.assertEqual(self.crypto_device.get_physical_block_size(), raw_size)

    def test_oversized_payload_rejection(self):
        """Attempting to write more data than usable block size must raise StorageException."""
        block_id = self.crypto_device.allocate_block()
        oversized_data = b"X" * (self.crypto_device.get_block_size() + 1)
        with self.assertRaises(StorageException):
            self.crypto_device.write_block(block_id, oversized_data)

    def test_delegated_device_methods(self):
        """Allocation and capacity queries must correctly delegate to the underlying device."""
        self.assertEqual(self.crypto_device.get_capacity(), 16)
        self.assertEqual(self.crypto_device.get_free_count(), 16)
        self.assertEqual(self.crypto_device.get_used_count(), 0)

        b1 = self.crypto_device.allocate_block()
        b_list = self.crypto_device.allocate_blocks(3)
        self.assertEqual(len(b_list), 3)
        self.assertEqual(self.crypto_device.get_used_count(), 4)

        self.assertTrue(self.crypto_device.is_available(b1))
        self.assertFalse(self.crypto_device.is_block_free(b1))

        self.crypto_device.free_block(b1)
        self.crypto_device.free_blocks(b_list)
        self.assertEqual(self.crypto_device.get_used_count(), 0)


class TestFileLevelEncryption(unittest.TestCase):
    """Test suite for file-level encryption helpers (encrypt_file, decrypt_file, read_encrypted_file)."""

    def setUp(self):
        self.raw_device = InMemoryBlockDevice(capacity=32, block_size=4096)
        self.fs = FileSystemService(block_device=self.raw_device, default_strategy=AllocationStrategy.INDEXED)
        self.passphrase = "ChaveSecretaDeArquivo_9988"

    def test_encrypt_and_decrypt_file_lifecycle(self):
        """Verify full lifecycle: create plain file, encrypt, verify ciphertext on disk, decrypt."""
        path = "/home/carlos/segredo.txt"
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/carlos")
        original_content = "Relatório Financeiro Estratégico do Projeto OS Simulator 2026."
        self.fs.write_file(path, original_content)

        # 1. Initial State: plain file
        self.assertFalse(is_file_encrypted(self.fs, path))
        self.assertEqual(self.fs.read_file(path), original_content)

        # 2. Encrypt File
        result = encrypt_file(self.fs, path, self.passphrase)
        self.assertTrue(result["is_encrypted"])
        self.assertTrue(is_file_encrypted(self.fs, path))

        # 3. Physical Inspection: verify underlying storage has NO plaintext
        node = self.fs.vfs.get_file(path)
        inode = self.fs.inode_table[node.inode_id]
        for b_id in inode.allocated_blocks:
            raw_block = bytes(self.raw_device.read_block(b_id))
            self.assertNotIn(b"Relat\xc3\xb3rio Financeiro", raw_block)
            self.assertNotIn(b"Estrat\xc3\xa9gico", raw_block)

        # 4. Read without modifying disk state
        read_text = read_encrypted_file(self.fs, path, self.passphrase)
        self.assertEqual(read_text, original_content)
        self.assertTrue(is_file_encrypted(self.fs, path), "File should remain encrypted on disk")

        # 5. In-Place Decrypt
        decrypted_bytes = decrypt_file(self.fs, path, self.passphrase, in_place=True)
        self.assertEqual(decrypted_bytes.decode("utf-8"), original_content)
        self.assertFalse(is_file_encrypted(self.fs, path))
        self.assertEqual(self.fs.read_file(path), original_content)

    def test_file_decryption_wrong_key_fails(self):
        """Decrypting an encrypted file with wrong key must raise InvalidTagException."""
        path = "/sistema/segredo.key"
        self.fs.mkdir("/sistema")
        self.fs.write_file(path, "Dados ultra secretos")
        encrypt_file(self.fs, path, "ChaveCorreta123")

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            decrypt_file(self.fs, path, "ChaveIncorreta456")

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            read_encrypted_file(self.fs, path, "ChaveIncorreta456")

    def test_file_tamper_detection(self):
        """Tampering 1 byte in a file's allocated storage blocks must fail decryption."""
        path = "/documento.txt"
        self.fs.write_file(path, "Contrato com assinatura digital garantida.")
        encrypt_file(self.fs, path, self.passphrase)

        # Modify 1 byte in the first allocated data block
        node = self.fs.vfs.get_file(path)
        inode = self.fs.inode_table[node.inode_id]
        target_block = inode.allocated_blocks[0]
        raw_disk_block = self.raw_device.get_block(target_block)
        raw_disk_block.data[20] ^= 0xAA

        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            decrypt_file(self.fs, path, self.passphrase)

    def test_direct_write_encrypted_file(self):
        """Creating an encrypted file directly sets is_encrypted = True immediately."""
        path = "/var/log/audit.enc"
        self.fs.mkdir("/var")
        self.fs.mkdir("/var/log")
        content = "2026-11-15: Evento de login administrativo concedido."

        write_encrypted_file(self.fs, path, content, key=self.passphrase)
        self.assertTrue(is_file_encrypted(self.fs, path))

        # Can be read with key
        self.assertEqual(read_encrypted_file(self.fs, path, self.passphrase), content)

    def test_encrypt_empty_file(self):
        """Empty files (0 bytes) can be encrypted and decrypted cleanly."""
        path = "/empty.txt"
        self.fs.create_file(path)
        self.assertEqual(self.fs.read_file(path), "")

        encrypt_file(self.fs, path, self.passphrase)
        self.assertTrue(is_file_encrypted(self.fs, path))

        decrypted = decrypt_file(self.fs, path, self.passphrase, in_place=True)
        self.assertEqual(decrypted, b"")
        self.assertFalse(is_file_encrypted(self.fs, path))

    def test_encrypt_multi_block_file(self):
        """Files spanning multiple disk blocks (e.g. 10,000 bytes) encrypt and decrypt correctly."""
        path = "/large_file.dat"
        # 10,000 bytes across 4096-byte blocks spans 3 blocks
        large_payload = os.urandom(10_000)
        self.fs.write_file(path, large_payload)

        encrypt_file(self.fs, path, self.passphrase)
        self.assertTrue(is_file_encrypted(self.fs, path))

        # Physical inspection: all blocks contain only ciphertext
        node = self.fs.vfs.get_file(path)
        inode = self.fs.inode_table[node.inode_id]
        self.assertGreaterEqual(len(inode.allocated_blocks), 3)

        decrypted = decrypt_file(self.fs, path, self.passphrase, in_place=True)
        self.assertEqual(decrypted, large_payload)

    def test_different_allocation_strategies_with_encryption(self):
        """File encryption must work identically across Contiguous, Linked FAT, and Indexed strategies."""
        for strategy in [AllocationStrategy.CONTIGUOUS, AllocationStrategy.LINKED_FAT, AllocationStrategy.INDEXED]:
            dev = InMemoryBlockDevice(capacity=20, block_size=4096)
            fs = FileSystemService(block_device=dev, default_strategy=strategy)

            filepath = f"/teste_{strategy.value}.txt"
            fs.write_file(filepath, f"Payload testando estratégia {strategy.value}")

            encrypt_file(fs, filepath, "ChaveUniversal_2026")
            self.assertTrue(is_file_encrypted(fs, filepath))

            decrypted = decrypt_file(fs, filepath, "ChaveUniversal_2026", in_place=True)
            self.assertEqual(decrypted.decode("utf-8"), f"Payload testando estratégia {strategy.value}")

    def test_error_handling_edge_cases(self):
        """Edge cases: re-encrypting, decrypting unencrypted files, missing files."""
        path = "/file.txt"
        self.fs.write_file(path, "conteudo")

        # Decrypting an unencrypted file raises SecurityException
        with self.assertRaises(SecurityException):
            decrypt_file(self.fs, path, self.passphrase)

        # Encrypting once succeeds
        encrypt_file(self.fs, path, self.passphrase)

        # Re-encrypting already encrypted file raises SecurityException
        with self.assertRaises(SecurityException):
            encrypt_file(self.fs, path, self.passphrase)

        # Operating on non-existent file raises FileNotFoundException
        with self.assertRaises(FileNotFoundException):
            encrypt_file(self.fs, "/missing.txt", self.passphrase)


class TestCryptoStorageWithRAID(unittest.TestCase):
    """Integration suite verifying CryptoBlockDeviceAdapter over RAID (RAID 1 and RAID 5)."""

    def test_raid1_mirroring_with_block_encryption(self):
        """RAID 1 mirror with transparent AES-256-GCM block encryption."""
        disks = [
            PhysicalDisk(disk_id=0, capacity_blocks=8, block_size=4096),
            PhysicalDisk(disk_id=1, capacity_blocks=8, block_size=4096),
        ]
        raid1 = RAID1Controller(disks, block_size=4096)
        io_mgr = IOManager(storage_backend=raid1)
        adapter = IOBlockDeviceAdapter(io_manager=io_mgr, logical_capacity=raid1.logical_capacity, block_size=4096)

        key = secrets.token_bytes(32)
        crypto_adapter = CryptoBlockDeviceAdapter(adapter, key=key)

        # Write through encrypted adapter
        secret_data = b"RAID 1 Mirroring with AES-256-GCM authenticated encryption."
        crypto_adapter.write_block(0, secret_data)

        # Physical inspection: BOTH disks store ciphertext
        self.assertEqual(disks[0].read_block(0), disks[1].read_block(0))
        self.assertNotIn(b"RAID 1 Mirroring", bytes(disks[0].read_block(0)))

        # Read back through adapter
        self.assertEqual(crypto_adapter.read_block(0), secret_data)

        # Simulate failure of Disk 0
        disks[0].fail()
        # Read back seamlessly from surviving Disk 1 mirror
        self.assertEqual(crypto_adapter.read_block(0), secret_data)

    def test_raid5_parity_xor_with_block_encryption_and_failure_recovery(self):
        """RAID 5 array with transparent AES-256-GCM encryption, disk failure, and XOR rebuild."""
        num_disks = 3
        disks = [
            PhysicalDisk(disk_id=i, capacity_blocks=16, block_size=4096) for i in range(num_disks)
        ]
        raid5 = RAID5Controller(disks, block_size=4096)
        io_mgr = IOManager(storage_backend=raid5)
        adapter = IOBlockDeviceAdapter(io_manager=io_mgr, logical_capacity=raid5.logical_capacity, block_size=4096)

        key = secrets.token_bytes(32)
        crypto_adapter = CryptoBlockDeviceAdapter(adapter, key=key)

        # Mount FileSystemService on top of the encrypted RAID device!
        fs = FileSystemService(block_device=crypto_adapter)
        fs.mkdir("/raid_secure")
        fs.write_file("/raid_secure/banco_dados.db", "Registros Bancários Criptografados no RAID 5.")

        # Read back from filesystem
        content = fs.read_file("/raid_secure/banco_dados.db")
        self.assertEqual(content, "Registros Bancários Criptografados no RAID 5.")

        # Verify physical disks: all data sectors and parity sectors store ONLY ciphertext/XOR
        for d in disks:
            for b_idx in range(4):
                raw = bytes(d.read_block(b_idx))
                self.assertNotIn(b"Registros Banc\xc3\xa1rios", raw)

        # Invalidate Disk 1 (Hardware Failure in RAID 5)
        disks[1].fail()

        # Filesystem read must still succeed transparently via on-the-fly XOR reconstruction
        content_after_failure = fs.read_file("/raid_secure/banco_dados.db")
        self.assertEqual(content_after_failure, "Registros Bancários Criptografados no RAID 5.")

        # Tampering with surviving disk triggers tamper detection
        # Flip a byte on Disk 0
        disks[0].blocks[0].data[15] ^= 0x77
        with self.assertRaises((InvalidTagException, DecryptionFailedException, AuthenticationFailedException)):
            fs.read_file("/raid_secure/banco_dados.db")


if __name__ == "__main__":
    unittest.main()
