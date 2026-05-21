"""Triage cases repository.

Persists cases, traces, reports and delivery info to MongoDB.
Falls back to an in-memory dict when Mongo is unreachable so the API
remains functional for the demo even if the DB is down.
"""

from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.db import mongo
from app.schemas.triage import TriageCase

log = get_logger(__name__)


class CasesRepo:
    def __init__(self) -> None:
        self._mem: dict[str, dict] = {}

    def _col(self):
        return mongo.db().cases if mongo.is_ready() else None

    async def create(self, case: TriageCase) -> None:
        doc = case.model_dump(mode="json")
        doc["_created_at"] = datetime.utcnow()
        col = self._col()
        if col is not None:
            try:
                await col.update_one({"case_id": case.case_id}, {"$set": doc}, upsert=True)
                return
            except Exception as e:
                log.warning("mongo_create_failed", error=str(e))
        self._mem[case.case_id] = doc

    async def update_status(self, case_id: str, status: str, error: str | None = None) -> None:
        update = {"status": status}
        if error:
            update["error"] = error
        col = self._col()
        if col is not None:
            try:
                await col.update_one({"case_id": case_id}, {"$set": update})
                return
            except Exception as e:
                log.warning("mongo_update_failed", error=str(e))
        if case_id in self._mem:
            self._mem[case_id].update(update)

    async def complete(self, case: TriageCase) -> None:
        doc = case.model_dump(mode="json")
        doc["status"] = "completed"
        doc["_completed_at"] = datetime.utcnow()
        col = self._col()
        if col is not None:
            try:
                await col.update_one({"case_id": case.case_id}, {"$set": doc}, upsert=True)
                return
            except Exception as e:
                log.warning("mongo_complete_failed", error=str(e))
        self._mem[case.case_id] = doc

    async def get(self, case_id: str) -> Optional[dict]:
        col = self._col()
        if col is not None:
            try:
                doc = await col.find_one({"case_id": case_id})
                if doc:
                    doc.pop("_id", None)
                    return doc
            except Exception as e:
                log.warning("mongo_get_failed", error=str(e))
        return self._mem.get(case_id)

    async def list_recent(self, limit: int = 20) -> list[dict]:
        col = self._col()
        if col is not None:
            try:
                cursor = col.find({}, {"_id": 0}).sort("_created_at", -1).limit(limit)
                return [doc async for doc in cursor]
            except Exception as e:
                log.warning("mongo_list_failed", error=str(e))
        return list(self._mem.values())[-limit:]

    async def record_jira_key(self, case_id: str, jira_key: str) -> None:
        """Persist the Jira ticket key associated with a case.

        Best-effort: Mongo failures fall back to the in-memory store so the
        frontend still sees the key while the case is alive in this process.
        """
        col = self._col()
        if col is not None:
            try:
                await col.update_one(
                    {"case_id": case_id}, {"$set": {"jira_key": jira_key}},
                )
                return
            except Exception as e:
                log.warning("mongo_jira_key_failed", error=str(e))
        if case_id in self._mem:
            self._mem[case_id]["jira_key"] = jira_key

    async def record_delivery(self, case_id: str, delivery: dict) -> None:
        col = self._col()
        if col is not None:
            try:
                await col.update_one({"case_id": case_id}, {"$set": {"delivery": delivery}})
                await mongo.db().delivery_log.insert_one({
                    "case_id": case_id,
                    "delivery": delivery,
                    "ts": datetime.utcnow(),
                })
                return
            except Exception as e:
                log.warning("mongo_delivery_failed", error=str(e))
        if case_id in self._mem:
            self._mem[case_id]["delivery"] = delivery


cases_repo = CasesRepo()
