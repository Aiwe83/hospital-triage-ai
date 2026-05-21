"""Servicio de recuperación de protocolos (RAG con Elasticsearch BM25).

Lo usa el nodo `protocol_researcher` del grafo de agentes. Recibe una
consulta libre (síntomas + categorías + red_flags concatenados) y
devuelve los N protocolos más relevantes con su score BM25.

¿Por qué `multi_match` con boost?
---------------------------------
Damos más peso a coincidencias en `title` y `symptoms` (boost ^2)
porque son los campos donde la query del paciente tiene más
probabilidad de matchear vocabulario relevante. `actions` se boostea
menos porque suelen contener jerga clínica que la query rara vez
incluye.

Tipo `best_fields`: se queda con la mejor coincidencia entre campos
en lugar de sumarlas — evita inflar el score por documentos largos
que repiten términos sin contexto.
"""

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db import elastic

log = get_logger(__name__)


async def search_protocols(query: str, limit: int = 3) -> list[dict]:
    """Busca los `limit` protocolos más relevantes para `query`.

    Devuelve lista vacía (no excepciones) cuando ES no está
    disponible — el nodo del grafo decide cómo seguir sin protocolos
    en lugar de romper el workflow entero.
    """
    if not elastic.is_ready():
        log.warning("protocol_search_skip", reason="elasticsearch_unavailable")
        return []

    s = get_settings()
    es = elastic.client()
    # Cuerpo de búsqueda BM25 con multi_match.
    body = {
        "size": limit,
        "query": {
            "multi_match": {
                "query": query,
                # `^2` = boost 2× sobre score natural del campo.
                "fields": ["title^2", "symptoms^2", "red_flags^1.5", "actions", "category"],
                "type": "best_fields",
            }
        },
    }
    try:
        result = await es.search(index=s.elasticsearch_index_protocols, body=body)
    except Exception as e:
        # Errores transitorios (timeout, refresh en curso) no deben
        # cortar el flujo. Logueamos y devolvemos vacío.
        log.warning("protocol_search_failed", error=str(e))
        return []

    # Normalizamos la respuesta de ES a una lista plana de dicts —
    # más fácil de serializar al frontend y al PDF.
    hits = result.get("hits", {}).get("hits", [])
    return [
        {
            "id": h["_id"],
            "score": h["_score"],
            "title": h["_source"].get("title"),
            "category": h["_source"].get("category"),
            "severity": h["_source"].get("severity"),
            "actions": h["_source"].get("actions"),
            "source": h["_source"].get("source"),
        }
        for h in hits
    ]
