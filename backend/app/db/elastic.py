"""Cliente Elasticsearch y gestión del índice de protocolos.

¿Por qué Elasticsearch aquí?
----------------------------
El `protocol_researcher_node` busca protocolos clínicos relevantes para
un caso. Usamos Elasticsearch con BM25 (no embeddings) porque:
  * Los protocolos son textos cortos con vocabulario muy específico —
    BM25 funciona excelente sin coste de re-indexar embeddings.
  * Latencia <50ms en local, ideal para demo en vivo.
  * Sin coste de API externa de embeddings.

Si en el futuro quisiéramos RAG semántico, Elasticsearch 8.x ya
soporta `dense_vector` y kNN — el cambio sería en el mapping, no en
la lógica de negocio.
"""

from elasticsearch import AsyncElasticsearch
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

# Singleton del cliente. `None` significa "no disponible" → el servicio
# de protocolos devuelve lista vacía y el resto del pipeline sigue.
_es: AsyncElasticsearch | None = None


def client() -> AsyncElasticsearch | None:
    """Devuelve el cliente o None si ES no arrancó."""
    return _es


def is_ready() -> bool:
    return _es is not None


async def connect() -> None:
    """Abre el cliente y verifica versión + índice de protocolos."""
    global _es
    s = get_settings()
    _es = AsyncElasticsearch(hosts=[s.elasticsearch_url], request_timeout=10)
    try:
        # `info()` es la forma estándar de comprobar handshake en ES.
        info = await _es.info()
        log.info("elasticsearch_connected", version=info["version"]["number"])
        await ensure_protocols_index()
    except Exception as e:
        # Si ES no responde, dejamos `_es = None` para que `is_ready()`
        # devuelva False y los consumidores degraden.
        log.warning("elasticsearch_unavailable", error=str(e))
        _es = None


async def disconnect() -> None:
    """Cierra el transporte HTTP del cliente al parar el backend."""
    global _es
    if _es is not None:
        await _es.close()
        _es = None


# Mapping del índice `hospital_protocols`:
#   * `text`    — analizado, tokenizado. Soporta búsqueda BM25.
#   * `keyword` — sin análisis, exacto. Usado para filtros / aggregations.
PROTOCOLS_MAPPING = {
    "mappings": {
        "properties": {
            "title":       {"type": "text"},
            "category":    {"type": "keyword"},   # cardiac, respiratory, etc.
            "severity":    {"type": "keyword"},
            "symptoms":    {"type": "text"},
            "red_flags":   {"type": "text"},
            "actions":     {"type": "text"},
            "source":      {"type": "keyword"},
        }
    }
}


async def ensure_protocols_index() -> None:
    """Crea el índice de protocolos si no existe.

    Idempotente: si ya está, no hace nada. El seeder
    `scripts/seed_protocols.py` se encarga de poblarlo.
    """
    if _es is None:
        return
    s = get_settings()
    exists = await _es.indices.exists(index=s.elasticsearch_index_protocols)
    if not exists:
        await _es.indices.create(index=s.elasticsearch_index_protocols, body=PROTOCOLS_MAPPING)
        log.info("protocols_index_created", name=s.elasticsearch_index_protocols)
