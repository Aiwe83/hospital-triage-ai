"""Serve the project handbook files (README.md, CLAUDE.md) as plain text.

The frontend `/docs` page fetches these so the demo audience can read the
project context without leaving the UI. The files are mounted read-only
inside the backend container by docker-compose (`/app/docs/*.md`). If the
mount is missing the endpoint returns a clear 404 instead of hanging.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/handbook", tags=["handbook"])


_FILES: dict[str, Path] = {
    "readme": Path("/app/docs/README.md"),
    "claude": Path("/app/docs/CLAUDE.md"),
}


@router.get("/", summary="List available handbook documents")
async def list_docs() -> dict:
    return {
        "items": [
            {"name": name, "path": str(path), "available": path.exists()}
            for name, path in _FILES.items()
        ]
    }


@router.get("/{name}", response_class=PlainTextResponse, summary="Read a handbook document")
async def read_doc(name: str) -> str:
    path = _FILES.get(name.lower())
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown handbook document '{name}'. Available: {list(_FILES)}",
        )
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Handbook file not mounted at {path}. "
                "Verify the docker-compose bind mounts for the backend service."
            ),
        )
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read handbook file: {e}")
