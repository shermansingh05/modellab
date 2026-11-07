"""Privileged routes need a bearer token. With no token configured they stay closed rather than open."""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def require_admin(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("MODELLAB_ADMIN_TOKEN")
    if not token:
        raise HTTPException(503, "privileged routes are disabled: set MODELLAB_ADMIN_TOKEN")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, "invalid or missing bearer token")
