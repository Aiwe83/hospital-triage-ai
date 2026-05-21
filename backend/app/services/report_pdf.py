"""Genera el PDF de soporte al triaje a partir del payload del informe."""

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.lib import colors
from xml.sax.saxutils import escape

from app.schemas.triage import TriageCase


def _cell(text, style):
    """Envuelve el texto de la celda en un Paragraph para que ReportLab
    haga word-wrap dentro del ancho de columna en lugar de desbordar el
    borde de la tabla."""
    return Paragraph(escape(str(text)) if text is not None else "—", style)


def render_triage_pdf(case: TriageCase) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=18, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceAfter=6)
    body = styles["BodyText"]
    # wordWrap=CJK fuerza cortes a nivel de carácter en tokens largos sin
    # espacios (URLs, IDs, palabras en castellano sin partir) para que
    # nunca se salgan de las celdas de la tabla.
    body_table = ParagraphStyle(
        "body_table", parent=body, fontSize=9, leading=11, wordWrap="CJK",
        spaceBefore=0, spaceAfter=0,
    )
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey, wordWrap="CJK")

    elements = []

    report = case.report
    intake = case.intake

    sex_label = {
        "male": "hombre",
        "female": "mujer",
        "other": "otro",
        "unknown": "desconocido",
    }.get(intake.sex or "unknown", intake.sex or "desconocido")
    arrival_label = {
        "walk_in": "por sus medios",
        "ambulance": "ambulancia",
        "transfer": "traslado",
    }.get(intake.arrival_mode or "walk_in", intake.arrival_mode or "por sus medios")

    elements.append(Paragraph("Hospital Triage IA — Informe de soporte a la decisión", title))
    elements.append(Paragraph(f"Identificador de caso: <b>{case.case_id}</b>", body))
    elements.append(Paragraph(f"Creado: {case.created_at.isoformat()}", small))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Recepción del paciente", h2))
    intake_pairs = [
        ("Edad", intake.age),
        ("Sexo", sex_label),
        ("Llegada", arrival_label),
        ("Síntomas", intake.symptoms),
        ("Antecedentes", intake.medical_history or "—"),
        ("Medicación", intake.medications or "—"),
        ("Alergias", intake.allergies or "—"),
    ]
    intake_rows = [[_cell(k, body_table), _cell(v, body_table)] for k, v in intake_pairs]
    t = Table(intake_rows, colWidths=[35 * mm, 135 * mm], repeatRows=0)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Constantes vitales", h2))
    v = intake.vital_signs
    v_pairs = [
        ("Constante", "Valor"),
        ("Frecuencia cardíaca (lpm)", v.heart_rate),
        ("Presión arterial (mmHg)", f"{v.blood_pressure_systolic}/{v.blood_pressure_diastolic}"),
        ("Frecuencia respiratoria (rpm)", v.respiratory_rate),
        ("SpO2 (%)", v.oxygen_saturation),
        ("Temperatura (°C)", v.temperature_celsius),
        ("Dolor (0-10)", v.pain_score),
    ]
    v_rows = [[_cell(k, body_table), _cell("—" if b is None else b, body_table)] for k, b in v_pairs]
    tv = Table(v_rows, colWidths=[60 * mm, 110 * mm])
    tv.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(tv)
    elements.append(Spacer(1, 10))

    priority_label = {
        "critical": "CRÍTICA",
        "urgent": "URGENTE",
        "standard": "ESTÁNDAR",
        "non_urgent": "NO URGENTE",
    }

    if report:
        elements.append(Paragraph("Prioridad sugerida", h2))
        priority_text = priority_label.get(
            report.suggested_priority, report.suggested_priority.upper()
        )
        elements.append(Paragraph(f"<b>{priority_text}</b>", body))
        elements.append(Spacer(1, 6))

        elements.append(Paragraph("Factores de riesgo", h2))
        if report.risk_factors:
            for rf in report.risk_factors:
                elements.append(Paragraph(f"• {rf}", body))
        else:
            elements.append(Paragraph("—", body))
        elements.append(Spacer(1, 6))

        elements.append(Paragraph("Próximos pasos sugeridos", h2))
        for ns in report.recommended_next_steps:
            elements.append(Paragraph(f"• {ns}", body))
        elements.append(Spacer(1, 6))

        elements.append(Paragraph("Protocolos recuperados", h2))
        if report.retrieved_protocols:
            for p in report.retrieved_protocols:
                score = p.get("score")
                score_txt = f" (puntuación {score:.2f})" if isinstance(score, (int, float)) else ""
                elements.append(Paragraph(f"• {p.get('title')}{score_txt}", body))
        else:
            elements.append(Paragraph("—", body))
        elements.append(Spacer(1, 6))

        elements.append(Paragraph("Resumen clínico", h2))
        elements.append(Paragraph(report.summary, body))
        elements.append(Spacer(1, 10))

    agent_es = {
        "triage_orchestrator": "Orquestador de triaje",
        "clinical_analyst": "Analista clínico",
        "protocol_researcher": "Investigador de protocolos",
        "hospital_systems_executor": "Sistemas hospitalarios",
        "clinical_safety_validator": "Validador de seguridad",
        "report_writer": "Redactor de informe",
    }
    status_es = {
        "idle": "en reposo",
        "receiving_case": "recibiendo caso",
        "thinking": "razonando",
        "walking": "en tránsito",
        "analyzing": "analizando",
        "searching": "buscando",
        "executing": "ejecutando",
        "validating": "validando",
        "writing": "redactando",
        "discussing": "deliberando",
        "completed": "completado",
        "blocked": "esperando",
        "error": "error",
    }

    elements.append(Paragraph("Traza de agentes", h2))
    for ev in case.agent_trace[-30:]:
        ts = ev.timestamp.isoformat(timespec="seconds") if ev.timestamp else ""
        agent_label = agent_es.get(ev.agent_id, ev.agent_id)
        status_label = status_es.get(ev.status, ev.status)
        elements.append(Paragraph(
            f"<b>{ts} — {agent_label}</b> [{status_label}] {ev.message}", small,
        ))

    elements.append(Spacer(1, 12))
    if report:
        elements.append(Paragraph(f"<i>{report.disclaimer}</i>", small))

    doc.build(elements)
    return buf.getvalue()
