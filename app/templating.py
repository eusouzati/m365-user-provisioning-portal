from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app import __version__
from app.auth import Roles
from app.core.workflow import ETAPA_STATUS_LABELS, STATUS_LABELS
from app.icons import icone

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals.update(version=__version__, Roles=Roles)


def _data_local(value, com_hora: bool = False) -> str:
    """Data/hora UTC → fuso configurado (TIMEZONE)."""
    from zoneinfo import ZoneInfo

    from app.config import get_settings

    try:
        tz = ZoneInfo(get_settings().timezone)
    except Exception:  # pragma: no cover
        tz = None
    local = value.astimezone(tz) if tz else value
    return local.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def _data_iso_local(value: str) -> str:
    """Texto ISO (estado salvo em JSON) → data/hora local."""
    from datetime import datetime

    try:
        return _data_local(datetime.fromisoformat(value), True)
    except (TypeError, ValueError):
        return "—"


templates.env.filters["data_local"] = _data_local
templates.env.filters["data_iso_local"] = _data_iso_local
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["etapa_labels"] = ETAPA_STATUS_LABELS


def _iniciais(nome: str) -> str:
    """Iniciais para o avatar ("Auto Silva" → "AS")."""
    partes = [p for p in (nome or "").split() if p[:1].isalnum()]
    if not partes:
        return "?"
    letras = partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")
    return letras.upper()


templates.env.globals["icone"] = icone
templates.env.globals["iniciais"] = _iniciais
