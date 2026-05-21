"""Pipeline de exportación de informes.

Modos:
  - mock:  escribe el PDF en REPORT_OUTPUT_DIR y loguea una trace de entrega.
  - drive: sube a Google Drive (requiere service account).
  - gmail: envía como adjunto de Gmail (requiere service account).

Para el MVP solo `mock` está cableado por completo — los otros son stubs
que registran el destino configurado para que el flujo de la demo siga
intacto cuando faltan credenciales.
"""

import os
from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.cases_repo import cases_repo
from app.schemas.triage import TriageCase
from app.services.report_pdf import render_triage_pdf

log = get_logger(__name__)


async def export_report(case: TriageCase) -> dict:
    s = get_settings()
    pdf = render_triage_pdf(case)

    # Escribir el artefacto en el dir de trabajo interno (fuera de la
    # carpeta sincronizada por Drive) para que el endpoint legacy
    # /export y la descarga /report.pdf nunca dejen un duplicado dentro
    # de la carpeta sincronizada de reports.
    out_dir = Path(s.report_internal_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"triage_{case.case_id}.pdf"
    pdf_path.write_bytes(pdf)

    delivery = {
        "mode": s.report_export_mode,
        "status": "delivered",
        "timestamp": datetime.utcnow().isoformat(),
        "artifact": {"type": "pdf", "path": str(pdf_path), "size_bytes": len(pdf)},
        "destination": None,
    }

    if s.report_export_mode == "drive":
        delivery["destination"] = {"type": "drive", "folder_id": s.google_drive_folder_id or None}
        if not s.google_service_account_json:
            delivery["status"] = "mock"
            delivery["note"] = "GOOGLE_SERVICE_ACCOUNT_JSON no configurado — subida a Drive simulada."
        else:
            # Subida real a Drive fuera del alcance del MVP. Marcado como diferido.
            delivery["status"] = "deferred"
            delivery["note"] = "Subida a Drive no implementada en el MVP. PDF guardado localmente."
    elif s.report_export_mode == "gmail":
        delivery["destination"] = {"type": "gmail", "to": s.report_recipient_email or None}
        if not s.google_service_account_json:
            delivery["status"] = "mock"
            delivery["note"] = "GOOGLE_SERVICE_ACCOUNT_JSON no configurado — envío por Gmail simulado."
        else:
            delivery["status"] = "deferred"
            delivery["note"] = "Envío por Gmail no implementado en el MVP. PDF guardado localmente."
    else:
        delivery["destination"] = {"type": "local", "path": str(pdf_path)}

    await cases_repo.record_delivery(case.case_id, delivery)
    log.info("report_exported", case_id=case.case_id, mode=delivery["mode"], status=delivery["status"])
    return delivery
