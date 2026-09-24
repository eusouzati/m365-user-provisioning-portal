from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import __version__
from app.dependencies import get_storage
from app.storage import StorageBackend

router = APIRouter(tags=["health"])
logger = logging.getLogger("m365up.health")


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: a aplicação está no ar (e qual versão — o deploy confere)."""
    return {"status": "healthy", "version": __version__}


@router.get("/health/ready")
def ready(storage: StorageBackend = Depends(get_storage)) -> JSONResponse:
    """Readiness: dependências (armazenamento) acessíveis. Não expõe detalhes de erro."""
    try:
        storage.ping()
    except Exception:
        logger.exception("Readiness falhou no armazenamento %s", storage.name)
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "storage": storage.name}
        )
    return JSONResponse(content={"status": "ready", "storage": storage.name})
