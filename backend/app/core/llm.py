"""Wrapper del cliente LLM.

Apunta a una pasarela compatible con OpenAI (proxy interno NextAI /
CodingBuddy). LangChain habla "dialecto OpenAI" — por eso podemos usar
`ChatOpenAI` aunque el backend real no sea OpenAI directamente.

Headers extra:
  La pasarela exige cabeceras propias (`apikey`, `provider`, `origin`,
  `email`) además del `Authorization: Bearer ...`. Sin ellas el proxy
  devuelve 401 incluso con un token válido.
"""

from functools import lru_cache
from langchain_openai import ChatOpenAI

from app.core.settings import get_settings


@lru_cache
def get_chat_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Devuelve un cliente Chat reutilizable (cacheado por temperatura).

    `@lru_cache` garantiza que la clase se construya UNA vez por
    temperatura — abrir un cliente HTTP por cada llamada al LLM sería
    desperdicio (cada uno crea su propio pool de conexiones).

    Temperature 0.2 = casi determinista. Usamos baja temperatura
    porque los nodos esperan JSON estructurado; una temperatura alta
    aumentaría la probabilidad de "alucinaciones de formato".
    """
    s = get_settings()
    # La pasarela Aigen / CodingBuddy requiere headers propios además
    # del bearer estándar. El bearer va automático con `api_key`.
    default_headers = {
        "apikey": s.llm_api_key,
        "provider": s.llm_provider,
        "origin": s.llm_origin,
        "origin-detail": s.llm_origin_detail,
    }
    # Email del usuario: lo manda el proxy para enrutado / cuota por usuario.
    if s.llm_user_email:
        default_headers["email"] = s.llm_user_email
        default_headers["X-User-Email"] = s.llm_user_email

    return ChatOpenAI(
        model=s.llm_model,
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        temperature=temperature,
        timeout=s.llm_timeout,
        default_headers=default_headers,
        max_retries=2,  # reintentos para errores transitorios (rate limit, 503)
    )
