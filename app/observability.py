"""Logging e Application Insights.

Regra do projeto: nunca registrar senhas, TAP, tokens ou segredos.
"""

from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger("m365up")


# Bibliotecas que registram cada chamada HTTP (com URLs que podem conter IDs, filtros
# de UPN etc.). Só avisos e erros: menos ruído, menos custo e menos dados pessoais.
NOISY_LOGGERS = (
    "azure",
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity",
    "azure.monitor",
    "httpx",
    "httpcore",
    "urllib3",
)


def configure_observability(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if not settings.applicationinsights_connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            logger_name="m365up",
            enable_live_metrics=False,  # sem "ping" a cada 5 s (QuickPulse)
        )
    except Exception:  # pragma: no cover - não derrubar a aplicação por telemetria
        logger.exception("Falha ao configurar o Application Insights")
