"""In-memory signing session manager for offline root CA key ceremonies.

Keys are held in memory only — never persisted to disk or database.
Sessions auto-expire after a configurable timeout (default 15 minutes).
"""

import threading
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import load_pem_private_key


@dataclass
class SigningSession:
    ca_id: str
    key: PrivateKeyTypes
    started_at: datetime
    expires_at: datetime
    started_by: str


class SigningSessionManager:
    """Thread-safe in-memory store for temporary CA signing keys."""

    def __init__(self) -> None:
        self._sessions: dict[str, SigningSession] = {}
        self._lock = threading.Lock()

    def start_session(
        self,
        ca_id: str,
        key_pem: bytes,
        key_password: str | None,
        timeout_minutes: int,
        username: str,
    ) -> SigningSession:
        """Load key into memory and start a timed session."""
        pwd = key_password.encode() if key_password else None
        try:
            key = load_pem_private_key(key_pem, password=pwd)
        except Exception as e:
            raise ValueError(f"Failed to load private key: {e}")

        now = datetime.now(timezone.utc)
        session = SigningSession(
            ca_id=ca_id,
            key=key,
            started_at=now,
            expires_at=now + timedelta(minutes=timeout_minutes),
            started_by=username,
        )

        with self._lock:
            self._sessions[ca_id] = session

        return session

    def get_session(self, ca_id: str) -> SigningSession | None:
        """Get active session for a CA, or None if expired/missing."""
        with self._lock:
            session = self._sessions.get(ca_id)
            if not session:
                return None
            now = datetime.now(timezone.utc)
            if now > session.expires_at:
                del self._sessions[ca_id]
                return None
            return session

    def end_session(self, ca_id: str) -> bool:
        """Explicitly end a session, removing the key from memory."""
        with self._lock:
            if ca_id in self._sessions:
                del self._sessions[ca_id]
                return True
            return False

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        now = datetime.now(timezone.utc)
        removed = 0
        with self._lock:
            expired = [k for k, v in self._sessions.items() if now > v.expires_at]
            for k in expired:
                del self._sessions[k]
                removed += 1
        return removed

    def active_sessions(self) -> list[dict]:
        """List active sessions (without exposing keys)."""
        now = datetime.now(timezone.utc)
        result = []
        with self._lock:
            for ca_id, s in self._sessions.items():
                if now <= s.expires_at:
                    result.append({
                        "ca_id": ca_id,
                        "started_by": s.started_by,
                        "started_at": s.started_at.isoformat(),
                        "expires_at": s.expires_at.isoformat(),
                        "remaining_seconds": int((s.expires_at - now).total_seconds()),
                    })
        return result


# Singleton instance
session_manager = SigningSessionManager()
