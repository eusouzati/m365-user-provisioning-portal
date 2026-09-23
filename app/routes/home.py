from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import Settings
from app.dependencies import get_app_settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def home(request: Request, settings: Settings = Depends(get_app_settings)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"settings": settings, "version": __version__},
    )
