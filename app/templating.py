from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app import __version__
from app.auth import Roles
from app.core.workflow import STATUS_LABELS

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


templates.env.filters["data_local"] = _data_local
templates.env.globals["status_labels"] = STATUS_LABELS
