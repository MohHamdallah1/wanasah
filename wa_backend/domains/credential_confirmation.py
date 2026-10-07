from __future__ import annotations

import asyncio

import bcrypt

from models import Driver


async def verify_actor_password(actor: Driver, password: str) -> bool:
    """Re-authenticate the already-authorized actor without persisting the secret."""
    if not isinstance(password, str) or not password or not actor.password_hash:
        return False
    try:
        return bool(await asyncio.to_thread(
            bcrypt.checkpw,
            password.encode("utf-8"),
            actor.password_hash.encode("utf-8"),
        ))
    except (ValueError, TypeError, UnicodeError):
        return False
