"""Endpoints chamados por automações (não por pessoas).

POST /interno/ciclo-de-vida — chamado de hora em hora pela Logic App usando a Managed
Identity (token para api://<client-id>) com o App Role Provisionamento.Agendador.
Esse papel só pode ser atribuído a aplicações, nunca a pessoas; por isso não há CSRF aqui.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth import Principal, Roles, require_roles
from app.config import Settings
from app.dependencies import get_app_settings, get_directory, get_storage, get_writer
from app.graph.directory import DirectoryCache
from app.graph.writer import GraphWriter
from app.services.lifecycle import LifecycleService
from app.storage import StorageBackend

router = APIRouter(prefix="/interno", include_in_schema=False)


@router.post("/ciclo-de-vida")
def run_lifecycle(
    settings: Settings = Depends(get_app_settings),
    writer: GraphWriter = Depends(get_writer),
    directory: DirectoryCache = Depends(get_directory),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(require_roles(Roles.AGENDADOR)),
) -> JSONResponse:
    report = LifecycleService(
        settings=settings, writer=writer, directory=directory, storage=storage
    ).run()
    return JSONResponse(report.as_dict())
