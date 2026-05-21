"""Configuración de logging estructurado con `structlog`.

¿Por qué structlog en vez de `logging` plano?
---------------------------------------------
Los logs salen como pares clave=valor (`agent_id=clinical_analyst
status=completed`) en vez de cadenas crudas. Eso permite:
  * Filtrar por campo en Grafana / Loki / ELK sin regex frágiles.
  * Mantener orden constante de campos (más fácil ojearlos).
  * Adjuntar contexto (`bind`) que aparece automáticamente en todas
    las llamadas siguientes del mismo logger.

Salida actual: ConsoleRenderer (texto coloreado para humanos). En
producción se puede cambiar a JSONRenderer sin tocar el código de los
módulos que loguean.
"""

import logging
import sys
import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configura tanto stdlib `logging` como `structlog`.

    Doble configuración: structlog envuelve a logging para no perder
    los logs de librerías terceras (uvicorn, httpx, etc.).
    """
    # `logging` estándar: salida raw a stdout (lo recoge Docker).
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    # `structlog`: pipeline de procesadores que enriquecen cada evento.
    structlog.configure(
        processors=[
            # Mergea contextvars (útil con request_id por petición).
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,        # añade `level=info|warning|...`
            structlog.processors.TimeStamper(fmt="iso"),  # timestamp ISO 8601
            structlog.processors.StackInfoRenderer(),  # stack si pides stack_info=True
            structlog.dev.ConsoleRenderer(colors=False),  # render para humanos
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        # Cachea el logger por nombre: rendimiento ↑, menos GC.
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """Atajo: `log = get_logger(__name__)` en cualquier módulo."""
    return structlog.get_logger(name)
