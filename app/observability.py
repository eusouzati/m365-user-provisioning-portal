"""Logging e Application Insights.

Regra do projeto: nunca registrar senhas, TAP, tokens ou segredos.
"""

from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger("m365up")


def configure_observability(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not settings.applicationinsights_connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            logger_name="m365up",
        )
    except Exception:  # pragma: no cover - não derrubar a aplicação por telemetria
        logger.exception("Falha ao configurar o Application Insights")
