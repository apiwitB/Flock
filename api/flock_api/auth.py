from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

ROLES = ("viewer", "investigator", "admin")
_hasher = PasswordHasher()
# ใช้เมื่อไม่พบชื่อผู้ใช้ เพื่อให้เวลาตอบใกล้เคียงกับกรณีรหัสผิด (ไม่บอกใบ้ว่าชื่อไหนมีอยู่)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class User:
    user_id: int
    username: str
    role: str

    def has_role(self, minimum: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(minimum)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    return _hasher.hash(password)


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def create_user(conn: psycopg.Connection, username: str, password: str, role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    row = conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING user_id",
        (username, hash_password(password), role),
    ).fetchone()
    return row[0]


def login(conn: psycopg.Connection, username: str, password: str, ttl: timedelta) -> tuple[str, User] | None:
    row = conn.execute(
        "SELECT user_id, username, role, password_hash, active FROM users WHERE username = %s", (username,)
    ).fetchone()
    try:
        _hasher.verify(row[3] if row else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return None
    if row is None or not row[4]:
        return None
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
        (_token_hash(token), row[0], ttl),
    )
    return token, User(row[0], row[1], row[2])


def user_for_token(conn: psycopg.Connection, token: str) -> User | None:
    row = conn.execute(
        """SELECT u.user_id, u.username, u.role FROM sessions s JOIN users u USING (user_id)
           WHERE s.token_hash = %s AND s.expires_at > now() AND u.active""",
        (_token_hash(token),),
    ).fetchone()
    return User(*row) if row else None


def logout(conn: psycopg.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))
