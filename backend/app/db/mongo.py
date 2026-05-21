"""Ciclo de vida del cliente MongoDB.

¿Qué guarda Mongo en este proyecto?
-----------------------------------
  * `cases` — un documento por caso de triaje (intake + trace + report + delivery).
  * `delivery_log` — auditoría de cada entrega a Drive (un doc por entrega).

Motor / motor_asyncio:
  Driver ASÍNCRONO de MongoDB. Permite hacer `await collection.find_one(...)`
  sin bloquear el event loop de FastAPI. Importante: no podemos usar
  `pymongo` directo aquí — bloquearía el loop.

Patrón singleton:
  Mantenemos `_client` y `_db` a nivel de módulo. El lifespan los abre
  al arrancar y los cierra al parar. Si Mongo no está disponible,
  `connect()` loguea warning pero NO levanta — el resto del backend
  sigue arrancando y cada operación cae al fallback in-memory.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

# Estado del singleton. `None` antes de connect() / después de disconnect().
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect() -> None:
    """Abre el cliente Motor y verifica conectividad con un `ping`.

    El `serverSelectionTimeoutMS=5000` evita que arranque cuelgue
    indefinidamente si la URI apunta a un host que no responde.
    """
    global _client, _db
    s = get_settings()
    _client = AsyncIOMotorClient(s.mongodb_uri, serverSelectionTimeoutMS=5000)
    _db = _client[s.mongodb_db]
    # `ping` confirma que el handshake funciona — falla rápida en
    # arranque si la URI es errónea o Mongo está caído.
    try:
        await _client.admin.command("ping")
        log.info("mongo_connected", uri=s.mongodb_uri, db=s.mongodb_db)
        await _ensure_indexes()
    except Exception as e:
        # NO levantamos: el repo cae al modo in-memory si Mongo no está.
        log.warning("mongo_unavailable", error=str(e))


async def disconnect() -> None:
    """Cierra el cliente al apagar el backend."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


def db() -> AsyncIOMotorDatabase:
    """Acceso al handle de la base de datos.

    Levanta `RuntimeError` si no se llamó a `connect()` antes; los
    consumidores deben comprobarlo con `is_ready()` y degradar.
    """
    if _db is None:
        raise RuntimeError("Mongo not connected")
    return _db


def is_ready() -> bool:
    """True si Mongo está conectado y listo para queries."""
    return _db is not None


async def _ensure_indexes() -> None:
    """Crea los índices que las queries esperan.

    Idempotente: Mongo ignora `create_index` si ya existe. Llamar en
    cada arranque es seguro y evita olvidos al desplegar.
    """
    if _db is None:
        return
    # `case_id` único → upserts por case_id no duplican.
    await _db.cases.create_index("case_id", unique=True)
    # `created_at` para `sort` en list_recent.
    await _db.cases.create_index("created_at")
    # `status` para filtros del dashboard ("dame los activos").
    await _db.cases.create_index("status")
    # `case_id` en delivery_log para joins por caso.
    await _db.delivery_log.create_index("case_id")
