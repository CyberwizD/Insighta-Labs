from __future__ import annotations

import secrets
import time
import uuid


def uuid7_str() -> str:
    """Generate a UUIDv7-compatible string."""
    ts_ms = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))
