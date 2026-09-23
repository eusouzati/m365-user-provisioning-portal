"""Geração de nomes de conta: Display Name, mailNickname, UPN e e-mail.

Regras (todas configuráveis e 100% testadas):
- remove acentos e caracteres especiais (João → joao, Conceição → conceicao, D'Ávila → davila);
- ignora partículas ("da", "de", "dos"...) ao escolher o sobrenome;
- padrão configurável, ex.: ``{nome}.{ultimo_sobrenome}`` → ``joao.silva``;
- colisões viram sufixo numérico: ``joao.silva``, ``joao.silva2``, ``joao.silva3``...
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_PATTERN = "{nome}.{ultimo_sobrenome}"
DEFAULT_PARTICLES = frozenset(
    {"da", "das", "de", "del", "der", "di", "do", "dos", "du", "e", "la", "le", "van", "von", "y"}
)
TOKENS = ("nome", "inicial_nome", "primeiro_sobrenome", "ultimo_sobrenome", "sobrenomes")
MAX_LOCAL_PART = 64
MAX_ATTEMPTS = 50

# Letras que a decomposição Unicode não separa em "base + acento"
_SPECIAL = str.maketrans(
    {
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "ø": "o",
        "Ø": "o",
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
        "œ": "oe",
        "Œ": "oe",
        "þ": "th",
    }
)


class NamingError(ValueError):
    pass


def ascii_fold(text: str) -> str:
    """Remove acentos: 'Conceição' → 'Conceicao'."""
    text = text.translate(_SPECIAL)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def slug(text: str) -> str:
    """Parte de nome → [a-z0-9-]: 'D'Ávila' → 'davila', 'Ana-Maria' → 'ana-maria'."""
    s = ascii_fold(text).lower()
    s = re.sub(r"['’`´]", "", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def split_words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def surname_parts(surname: str, particles: frozenset[str] = DEFAULT_PARTICLES) -> list[str]:
    """Sobrenomes significativos (sem partículas), já normalizados."""
    parts = [slug(w) for w in split_words(surname)]
    meaningful = [p for p in parts if p and p not in particles]
    return meaningful or [p for p in parts if p]


def validate_pattern(pattern: str) -> str:
    found = re.findall(r"\{([^{}]*)\}", pattern)
    if not found:
        raise NamingError("O padrão de UPN precisa de ao menos um campo, ex.: {nome}")
    unknown = [t for t in found if t not in TOKENS]
    if unknown:
        raise NamingError(f"Campos desconhecidos no padrão de UPN: {', '.join(unknown)}")
    literal = re.sub(r"\{[^{}]*\}", "", pattern)
    if re.search(r"[^a-z0-9._-]", literal):
        raise NamingError("O padrão de UPN só pode conter . _ - entre os campos")
    return pattern


def clean_local_part(value: str) -> str:
    v = re.sub(r"[^a-z0-9._-]", "", value.lower())
    v = re.sub(r"([._-])[._-]+", r"\1", v)  # separadores repetidos
    return v.strip("._-")[:MAX_LOCAL_PART].rstrip("._-")


def build_local_part(
    first_name: str,
    surname: str,
    pattern: str = DEFAULT_PATTERN,
    particles: frozenset[str] = DEFAULT_PARTICLES,
) -> str:
    validate_pattern(pattern)
    first = [slug(w) for w in split_words(first_name) if slug(w)]
    surnames = surname_parts(surname, particles)
    if not first:
        raise NamingError("O nome não contém letras utilizáveis para gerar o login")
    if not surnames:
        raise NamingError("O sobrenome não contém letras utilizáveis para gerar o login")
    values = {
        "nome": first[0],
        "inicial_nome": first[0][0],
        "primeiro_sobrenome": surnames[0],
        "ultimo_sobrenome": surnames[-1],
        "sobrenomes": ".".join(surnames),
    }
    local = clean_local_part(re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], pattern))
    if not local:
        raise NamingError("Não foi possível gerar um login válido a partir do nome")
    return local


def candidates(base: str, limit: int = MAX_ATTEMPTS):
    """joao.silva, joao.silva2, joao.silva3, ..."""
    yield base
    for i in range(2, limit + 1):
        suffix = str(i)
        yield base[: MAX_LOCAL_PART - len(suffix)].rstrip("._-") + suffix


def display_name(first_name: str, surname: str) -> str:
    return " ".join(split_words(f"{first_name} {surname}"))


@dataclass(frozen=True)
class AccountNames:
    display_name: str
    given_name: str
    surname: str
    mail_nickname: str
    user_principal_name: str
    mail: str
    base_local_part: str
    attempts: int  # quantas colisões foram evitadas (0 = nome base livre)

    @property
    def renamed(self) -> bool:
        return self.attempts > 0


def generate_account_names(
    *,
    first_name: str,
    surname: str,
    domain: str,
    is_taken: Callable[[str, str], bool],
    display: str | None = None,
    pattern: str = DEFAULT_PATTERN,
    particles: frozenset[str] = DEFAULT_PARTICLES,
    limit: int = MAX_ATTEMPTS,
) -> AccountNames:
    """Gera os nomes e escolhe o primeiro endereço livre.

    ``is_taken(endereco, mail_nickname)`` deve consultar o diretório (UPN, e-mail,
    mailNickname e proxyAddresses de usuários e grupos).
    """
    domain = domain.strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", domain):
        raise NamingError("Domínio padrão inválido")
    base = build_local_part(first_name, surname, pattern, particles)
    for attempt, local in enumerate(candidates(base, limit)):
        address = f"{local}@{domain}"
        if not is_taken(address, local):
            return AccountNames(
                display_name=display.strip()
                if display and display.strip()
                else display_name(first_name, surname),
                given_name=" ".join(split_words(first_name)),
                surname=" ".join(split_words(surname)),
                mail_nickname=local,
                user_principal_name=address,
                mail=address,
                base_local_part=base,
                attempts=attempt,
            )
    raise NamingError(f"Não há login livre após {limit} tentativas para '{base}'")
