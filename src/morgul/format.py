"""MORGUL on-disk container: versioned Argon2id + XChaCha20-Poly1305 + zstd.

File layout (all multi-byte fields are opaque blobs, not integers):

    version:u8 | salt | nonce | ciphertext_with_tag

Version ``0x00`` parameters live only in :data:`FORMATS` — unknown versions
are rejected so the header cannot negotiate weaker crypto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import zstandard as zstd
from argon2.low_level import Type, hash_secret_raw
from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
)
from nacl.exceptions import CryptoError

CURRENT_VERSION = 0x00


@dataclass(frozen=True, slots=True)
class FormatConfig:
    """Crypto + compression parameters for one MORGUL format revision."""

    argon2_time_cost: int
    argon2_memory_kib: int
    argon2_parallelism: int
    argon2_hash_len: int
    salt_len: int
    nonce_len: int
    zstd_level: int


# Only listed revisions are valid. Do not invent parameters at read time.
FORMATS: dict[int, FormatConfig] = {
    0x00: FormatConfig(
        argon2_time_cost=3,
        argon2_memory_kib=64 * 1024,  # 64 MiB
        argon2_parallelism=4,
        argon2_hash_len=32,
        salt_len=16,
        nonce_len=24,  # XChaCha20-Poly1305 IETF
        zstd_level=3,
    ),
}


class MorgulFormatError(ValueError):
    """Corrupt header, unknown version, or failed authentication."""


def is_morgul_path(path: object) -> bool:
    """Return True when *path* looks like a ``.morgul`` file."""
    name = str(path).lower()
    return name.endswith(".morgul")


def _derive_key(password: str, salt: bytes, cfg: FormatConfig) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=cfg.argon2_time_cost,
        memory_cost=cfg.argon2_memory_kib,
        parallelism=cfg.argon2_parallelism,
        hash_len=cfg.argon2_hash_len,
        type=Type.ID,
    )


def pack(markdown: str, password: str, *, version: int = CURRENT_VERSION) -> bytes:
    """Compress and encrypt *markdown* under *password*.

    Returns:
        A complete MORGUL file blob.

    Raises:
        MorgulFormatError: If *version* is not in :data:`FORMATS`.
        ValueError: If *password* is empty.
    """
    if not password:
        msg = "Password must not be empty for MORGUL packing."
        raise ValueError(msg)
    cfg = FORMATS.get(version)
    if cfg is None:
        msg = f"Unknown MORGUL format version: 0x{version:02x}"
        raise MorgulFormatError(msg)

    plain = markdown.encode("utf-8")
    compressed = zstd.ZstdCompressor(level=cfg.zstd_level).compress(plain)
    salt = os.urandom(cfg.salt_len)
    nonce = os.urandom(cfg.nonce_len)
    key = _derive_key(password, salt, cfg)
    aad = bytes([version])
    ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(
        compressed,
        aad,
        nonce,
        key,
    )
    return bytes([version]) + salt + nonce + ciphertext


def unpack(blob: bytes, password: str) -> str:
    """Decrypt and decompress a MORGUL *blob*.

    Returns:
        UTF-8 Markdown source.

    Raises:
        MorgulFormatError: Bad header, unknown version, or wrong password.
    """
    if len(blob) < 1:
        msg = "File is empty."
        raise MorgulFormatError(msg)
    version = blob[0]
    cfg = FORMATS.get(version)
    if cfg is None:
        msg = f"Unknown MORGUL format version: 0x{version:02x}"
        raise MorgulFormatError(msg)

    header = 1 + cfg.salt_len + cfg.nonce_len
    if len(blob) < header + 16:  # Poly1305 tag is 16 bytes minimum
        msg = "File is truncated."
        raise MorgulFormatError(msg)

    salt = blob[1 : 1 + cfg.salt_len]
    nonce = blob[1 + cfg.salt_len : header]
    ciphertext = blob[header:]
    key = _derive_key(password, salt, cfg)
    aad = bytes([version])
    try:
        compressed = crypto_aead_xchacha20poly1305_ietf_decrypt(
            ciphertext,
            aad,
            nonce,
            key,
        )
    except CryptoError as exc:
        msg = "Incorrect password or corrupted file."
        raise MorgulFormatError(msg) from exc

    try:
        plain = zstd.ZstdDecompressor().decompress(compressed)
    except zstd.ZstdError as exc:
        msg = "Decompression failed; file may be corrupted."
        raise MorgulFormatError(msg) from exc

    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "Decrypted payload is not valid UTF-8."
        raise MorgulFormatError(msg) from exc


def looks_like_morgul(blob: bytes) -> bool:
    """Heuristic: first byte is a known format version and length is plausible.

    Returns:
        True when *blob* could be a MORGUL container.
    """
    if not blob:
        return False
    cfg = FORMATS.get(blob[0])
    if cfg is None:
        return False
    return len(blob) >= 1 + cfg.salt_len + cfg.nonce_len + 16
