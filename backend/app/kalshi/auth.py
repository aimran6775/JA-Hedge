"""
JA Hedge — Kalshi RSA-PSS Authentication.

Generates signed headers for every Kalshi API request.
Private key is loaded once and held in memory for < 1ms signature generation.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.logging_config import get_logger

log = get_logger("kalshi.auth")


class KalshiAuth:
    """
    RSA-PSS request signer for Kalshi API.

    Usage:
        auth = KalshiAuth(key_id="abc123", private_key_path="./keys/kalshi.pem")
        headers = auth.sign("GET", "/trade-api/v2/portfolio/balance")
        # → {'KALSHI-ACCESS-KEY': ..., 'KALSHI-ACCESS-SIGNATURE': ..., 'KALSHI-ACCESS-TIMESTAMP': ...}
    """

    def __init__(self, key_id: str, private_key_path: str | Path):
        self._key_id = key_id
        self._private_key = self._load_key(Path(private_key_path))
        log.info("kalshi_auth_initialized", key_id=key_id[:8] + "..." if len(key_id) > 8 else key_id)

    @staticmethod
    def _load_key(path: Path) -> rsa.RSAPrivateKey:
        """Load RSA private key from PEM file. Called once at init."""
        if not path.exists():
            log.warning("private_key_not_found", path=str(path))
            raise FileNotFoundError(f"Kalshi private key not found: {path}")

        with open(path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)

        if not isinstance(key, rsa.RSAPrivateKey):
            raise TypeError(f"Expected RSA private key, got {type(key).__name__}")

        log.info("private_key_loaded", path=str(path))
        return key

    def sign(self, method: str, path: str) -> dict[str, str]:
        """
        Generate signed headers for a Kalshi API request.

        Args:
            method: HTTP method (GET, POST, DELETE, PUT)
            path: Request path WITHOUT query params (e.g., "/trade-api/v2/markets")

        Returns:
            Dict of headers to merge into request.

        Performance: < 1ms (RSA-PSS sign is ~0.3ms on modern hardware)
        """
        # Strip query parameters if accidentally included
        clean_path = path.split("?")[0]

        # Timestamp in milliseconds
        timestamp_ms = str(int(time.time() * 1000))

        # Message: timestamp + METHOD + path
        message = f"{timestamp_ms}{method.upper()}{clean_path}"

        # Sign with RSA-PSS + SHA256
        signature = self._private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    @property
    def key_id(self) -> str:
        return self._key_id


class NoAuth:
    """
    Stub auth for unauthenticated endpoints (public market data).
    Returns empty headers.
    """

    def sign(self, method: str, path: str) -> dict[str, str]:
        return {}

    @property
    def key_id(self) -> str:
        return ""
