"""Bus de eventos en proceso.

Cada caso de triaje en ejecución tiene una asyncio.Queue propia. Los nodos
de LangGraph publican objetos AgentEvent y el endpoint SSE los consume.
"""

import asyncio
from typing import Dict

from app.schemas.triage import AgentEvent


class EventBus:
    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue[AgentEvent | None]] = {}

    def open(self, case_id: str) -> asyncio.Queue:
        if case_id not in self._queues:
            self._queues[case_id] = asyncio.Queue()
        return self._queues[case_id]

    def get(self, case_id: str) -> asyncio.Queue | None:
        return self._queues.get(case_id)

    async def publish(self, case_id: str, event: AgentEvent) -> None:
        q = self.open(case_id)
        await q.put(event)

    async def close(self, case_id: str) -> None:
        q = self._queues.get(case_id)
        if q is not None:
            await q.put(None)  # sentinela
            # mantener la cola un rato por si llegan consumidores tardíos

    def drop(self, case_id: str) -> None:
        self._queues.pop(case_id, None)


bus = EventBus()
