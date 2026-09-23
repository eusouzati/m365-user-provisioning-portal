"""Senha temporária forte. Ela é enviada ao Graph e descartada: nunca é exibida,
registrada em log ou armazenada. O acesso inicial será por Temporary Access Pass (Sprint 7)."""

from __future__ import annotations

import secrets
import string

_SETS = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "!@#$%&*-_=+?")


def generate_password(length: int = 24) -> str:
    if length < 16:
        raise ValueError("A senha temporária deve ter ao menos 16 caracteres")
    chars = [secrets.choice(s) for s in _SETS]
    alphabet = "".join(_SETS)
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
