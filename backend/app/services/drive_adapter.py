"""Abstracción del adapter de Drive.

Diseño MVP (deliberadamente mínimo):

  * `McpDriveAdapter` — **por defecto**. Escribe el PDF en una ruta de
    trabajo bajo `REPORT_OUTPUT_DIR/internal/` y pide al servidor MCP
    interno que lo copie a la carpeta sincronizada por Drive Desktop vía
    la herramienta `send_report_to_drive`. Google Drive Desktop sincroniza
    luego la carpeta destino a la nube automáticamente — sin Google API,
    OAuth, service account ni credenciales.

  * `MockDriveAdapter` — se usa solo cuando MCP está deshabilitado o
    inalcanzable. Escribe el PDF en disco y devuelve un file_id sintético
    para que la demo siga funcionando sin infraestructura.

El servidor MCP es el **único** componente que toca la carpeta
sincronizada. Eso mantiene la integración auditable: el tutor inspecciona
una sola herramienta y una sola llamada HTTP.
"""

from __future__ import annotations

import asyncio
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


@dataclass
class UploadResult:
    mode: str               # "mock" | "local_sync"
    drive_file_id: str | None
    drive_view_url: str | None
    folder: str | None
    size_bytes: int
    path: str | None
    note: str = ""


class DriveAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    async def upload(
        self,
        *,
        filename: str,
        content: bytes,
        patient_id: str,
        mime: str = "application/pdf",
    ) -> UploadResult:
        ...


# ----------------------------------------------------------------------------
# Adapter mock (solo fallback)
# ----------------------------------------------------------------------------

class MockDriveAdapter(DriveAdapter):
    name = "mock"

    async def upload(
        self,
        *,
        filename: str,
        content: bytes,
        patient_id: str,
        mime: str = "application/pdf",
    ) -> UploadResult:
        s = get_settings()
        out_dir = Path(s.report_output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / filename
        path.write_bytes(content)

        await asyncio.sleep(0.4)
        await asyncio.sleep(0.4)
        await asyncio.sleep(0.5)

        file_id = f"sim-{secrets.token_urlsafe(10)}"
        view_url = f"https://drive.google.com/file/d/{file_id}/view"

        log.info("mock_drive_upload", filename=filename, file_id=file_id, size=len(content))
        return UploadResult(
            mode="mock",
            drive_file_id=file_id,
            drive_view_url=view_url,
            folder=str(out_dir),
            size_bytes=len(content),
            path=str(path),
            note=(
                "Modo simulado: el MCP server no está disponible. "
                "El PDF se ha escrito localmente para preservar el flujo de la demo."
            ),
        )


# ----------------------------------------------------------------------------
# Adapter MCP — sync con Drive Desktop vía herramienta MCP interna
# ----------------------------------------------------------------------------

class McpDriveAdapter(DriveAdapter):
    """Entrega el PDF a la herramienta MCP interna `send_report_to_drive`.

    Flujo:
      1. Persistir el PDF en `<reports>/internal/triage_<case_id>.pdf`.
      2. POST `{report_path, patient_id, optional_filename}` al servidor
         MCP. La herramienta MCP valida, copia a DRIVE_SYNC_FOLDER y
         renombra a la forma canónica `informe_<patient>_<ts>.pdf`.
      3. Drive Desktop (corriendo en el host) detecta el nuevo archivo en
         la carpeta sincronizada y lo empuja a Google Drive sin que
         nosotros toquemos la Google API.

    Ante un fallo del MCP seguimos guardando el PDF en disco para que un
    rescate manual sea trivial; la respuesta entonces aparece en modo
    `mock` con una nota clara.
    """

    name = "mcp"

    async def upload(
        self,
        *,
        filename: str,
        content: bytes,
        patient_id: str,
        mime: str = "application/pdf",
    ) -> UploadResult:
        s = get_settings()

        # Paso 1 — escribir el PDF fuente en una carpeta de trabajo que
        # vive FUERA de la carpeta sincronizada por Drive. Drive Desktop
        # no debe ver nunca esta copia de trabajo, si no cada entrega
        # produciría dos archivos en la nube (el fuente interno + el
        # destino renombrado).
        internal_dir = Path(s.report_internal_dir)
        internal_dir.mkdir(parents=True, exist_ok=True)
        source_path = internal_dir / filename
        source_path.write_bytes(content)
        log.info(
            "mcp_drive_source_written",
            source=str(source_path),
            size=len(content),
        )

        # Paso 2 — llamar a la herramienta MCP.
        url = f"{s.mcp_server_url.rstrip('/')}/tools/send_report_to_drive"
        payload = {
            "report_path": str(source_path),
            "patient_id": patient_id,
            "optional_filename": None,
        }

        try:
            async with httpx.AsyncClient(timeout=s.mcp_drive_timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            log.warning("mcp_drive_unreachable", url=url, error=str(e))
            return _fallback_mock_result(
                source_path=source_path,
                content_size=len(content),
                reason=(
                    f"No se pudo contactar al MCP server en {url}: {e}. "
                    "El PDF se guardó localmente."
                ),
            )

        if response.status_code != 200:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = response.text
            log.warning(
                "mcp_drive_error",
                status=response.status_code,
                detail=detail,
            )
            return _fallback_mock_result(
                source_path=source_path,
                content_size=len(content),
                reason=(
                    f"MCP send_report_to_drive respondió {response.status_code}: {detail}. "
                    "El PDF se guardó localmente."
                ),
            )

        data = response.json()
        dest_path = data.get("destination_path")
        dest_filename = data.get("filename")
        folder = data.get("drive_sync_folder")
        size_bytes = int(data.get("size_bytes") or len(content))

        log.info(
            "mcp_drive_local_sync_ok",
            destination_path=dest_path,
            filename=dest_filename,
            folder=folder,
        )

        # Paso 3 — borrar la copia de trabajo interna ahora que el destino
        # canónico es el dueño del artefacto. Mantiene la carpeta
        # sincronizada con exactamente un PDF por entrega; el dir interno
        # no se sincroniza igualmente, pero limpiarlo evita que el uso de
        # disco crezca a lo largo de muchos casos.
        try:
            source_path.unlink(missing_ok=True)
        except OSError as cleanup_err:
            log.warning(
                "mcp_drive_source_cleanup_failed",
                path=str(source_path),
                error=str(cleanup_err),
            )

        # `drive_file_id` aquí es un identificador *local* — exponemos el
        # filename para que la UI / tutor pueda localizar el archivo
        # dentro de la carpeta sincronizada. `drive_view_url` se queda en
        # None porque la URL real en la nube la produce Drive Desktop de
        # forma asíncrona y no consultamos la Drive API. El usuario puede
        # abrir la carpeta directamente desde Drive.
        return UploadResult(
            mode="local_sync",
            drive_file_id=dest_filename,
            drive_view_url=None,
            folder=folder,
            size_bytes=size_bytes,
            path=dest_path,
            note=(
                "PDF copiado a la carpeta sincronizada por Google Drive Desktop. "
                "La sincronización a la nube la realiza el cliente nativo de Drive en segundo plano."
            ),
        )


def _fallback_mock_result(*, source_path: Path, content_size: int, reason: str) -> UploadResult:
    file_id = f"sim-{secrets.token_urlsafe(10)}"
    return UploadResult(
        mode="mock",
        drive_file_id=file_id,
        drive_view_url=f"https://drive.google.com/file/d/{file_id}/view",
        folder=str(source_path.parent),
        size_bytes=content_size,
        path=str(source_path),
        note=reason,
    )


# ----------------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------------


def get_drive_adapter() -> DriveAdapter:
    s = get_settings()
    if s.mcp_enabled:
        return McpDriveAdapter()
    return MockDriveAdapter()
