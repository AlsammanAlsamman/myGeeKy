"""Private signals: only the person a signal is for can read it.

Each Signals user has an X25519 key pair per computer. The public half is
published in their beacon; the private half never leaves that computer's OS
keyring. A signal is sealed to the recipient's public key (an ECIES "sealed
box"):

    ephemeral X25519 key  ->  shared secret with the recipient's key
    HKDF-SHA256(shared, info = label | ephemeral pub | recipient pub)  ->  key
    ChaCha20-Poly1305(key, zero nonce -- every key is used exactly once)

    box = base64(ephemeral pub (32 bytes) || ciphertext + tag)

The plaintext is padded to a fixed size, so every box is the same length and
even the kind of signal can't be guessed from it. Nobody but the recipient
learns who a box is for, what it says, or that it was ever opened.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LABEL = b"mygeeky-signal-v2"
PAD_TO = 256                     # plaintext bytes in every box
BOX_LEN = len(base64.b64encode(b"\0" * (32 + PAD_TO + 16)))
_NONCE = b"\0" * 12
_RAW = serialization.Encoding.Raw


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes | None:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None


def new_keypair() -> tuple[str, str]:
    """(private, public), both base64 of the raw 32-byte keys."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    raw = priv.private_bytes(_RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return _b64(raw), _b64(pub)


def public_of(private_b64: str) -> str:
    priv = X25519PrivateKey.from_private_bytes(_unb64(private_b64) or b"")
    return _b64(priv.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw))


def valid_public_key(value: object) -> bool:
    raw = _unb64(value) if isinstance(value, str) and len(value) == 44 else None
    return raw is not None and len(raw) == 32


def _key(shared: bytes, eph_pub: bytes, recipient_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=LABEL + eph_pub + recipient_pub).derive(shared)


def seal(recipient_pub_b64: str, plaintext: bytes) -> str:
    if len(plaintext) > PAD_TO:
        raise ValueError("signal too long to seal")
    recipient_pub = _unb64(recipient_pub_b64)
    if recipient_pub is None or len(recipient_pub) != 32:
        raise ValueError("not a public key")
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    shared = eph.exchange(X25519PublicKey.from_public_bytes(recipient_pub))
    padded = plaintext + b"\0" * (PAD_TO - len(plaintext))
    return _b64(eph_pub + ChaCha20Poly1305(_key(shared, eph_pub, recipient_pub)).encrypt(_NONCE, padded, LABEL))


def open_box(private_b64: str, box_b64: object) -> bytes | None:
    """The plaintext if this box was sealed to our key, else None (never raises)."""
    if not isinstance(box_b64, str) or len(box_b64) != BOX_LEN:
        return None
    data = _unb64(box_b64)
    raw_priv = _unb64(private_b64)
    if data is None or raw_priv is None or len(data) < 32 + 16:
        return None
    try:
        priv = X25519PrivateKey.from_private_bytes(raw_priv)
        eph_pub, body = data[:32], data[32:]
        my_pub = priv.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
        shared = priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
        padded = ChaCha20Poly1305(_key(shared, eph_pub, my_pub)).decrypt(_NONCE, body, LABEL)
    except (InvalidTag, ValueError):
        return None
    return padded.rstrip(b"\0")
