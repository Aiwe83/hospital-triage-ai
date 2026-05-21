"""Pobla el índice Elasticsearch de protocolos con protocolos de triaje sintéticos.

Ejecutar dentro del contenedor backend:
    python -m scripts.seed_protocols
"""

import asyncio
from elasticsearch import AsyncElasticsearch
from app.core.settings import get_settings
from app.db.elastic import PROTOCOLS_MAPPING


PROTOCOLS = [
    {
        "id": "esi-1-via-aerea",
        "title": "ESI Nivel 1 — Intervención inmediata para salvar la vida",
        "category": "airway_breathing_circulation",
        "severity": "critical",
        "symptoms": "Paciente inconsciente, distrés respiratorio grave, compromiso de la vía aérea, parada cardíaca, shock grave, hemorragia mayor activa",
        "red_flags": "GCS<9, SpO2<90 con oxígeno, apnea, respiración agónica, bradipnea grave, cianosis, ausencia de pulso palpable",
        "actions": "Médico y enfermería en cabecera de forma inmediata. Soporte de vía aérea. Acceso intravenoso. Monitorización continua. Activar equipo de reanimación.",
        "source": "ESI v4 (síntesis didáctica)",
    },
    {
        "id": "esi-2-respiratorio",
        "title": "ESI Nivel 2 — Distrés respiratorio de alto riesgo",
        "category": "respiratory",
        "severity": "urgent",
        "symptoms": "Disnea en reposo, sibilancias, uso de musculatura accesoria, tos productiva, opresión torácica, hipoxia",
        "red_flags": "SpO2 90-94 con aire ambiente, FR>24, antecedente de asma grave o EPOC, intubación reciente",
        "actions": "Triaje en menos de 10 minutos. Oxígeno si SpO2<94. Broncodilatadores nebulizados según protocolo. ECG y radiografía de tórax. Considerar gasometría arterial.",
        "source": "ESI v4 (síntesis didáctica)",
    },
    {
        "id": "manchester-dolor-toracico",
        "title": "Manchester — Vía clínica del dolor torácico",
        "category": "cardiac",
        "severity": "urgent",
        "symptoms": "Dolor torácico central, irradiación a brazo o mandíbula, sudoración profusa, náuseas, disnea, palpitaciones",
        "red_flags": "Dolor >20 min sin alivio con reposo, hipotensión, síncope, cardiopatía isquémica conocida, edad>50 con factores de riesgo",
        "actions": "ECG en los primeros 10 minutos. Troponina. Aspirina si no está contraindicada. Interconsulta a Cardiología. Monitorización continua.",
        "source": "Sistema Manchester de Triaje (síntesis didáctica)",
    },
    {
        "id": "ictus-protocolo-fast",
        "title": "Ictus agudo — Protocolo FAST",
        "category": "neurological",
        "severity": "critical",
        "symptoms": "Asimetría facial súbita, debilidad de extremidad, alteración del habla, pérdida de visión, cefalea súbita intensa, hipoestesia unilateral",
        "red_flags": "Último momento asintomático <4,5 h, NIHSS≥4, anticoagulación oral, antecedente de fibrilación auricular",
        "actions": "Activar código ictus. TC craneal sin contraste en los primeros 25 minutos. Glucemia, INR, plaquetas. Evitar descensos agresivos de la presión arterial.",
        "source": "Guías AHA de ictus (síntesis didáctica)",
    },
    {
        "id": "sepsis-cribado",
        "title": "Cribado de sepsis (qSOFA / SIRS)",
        "category": "infection_sepsis",
        "severity": "urgent",
        "symptoms": "Fiebre, escalofríos, hipotensión, taquicardia, alteración del estado mental, oliguria, foco infeccioso sospechado",
        "red_flags": "qSOFA≥2 (FR≥22, PAS≤100, alteración del estado mental), lactato>2, cirugía reciente, inmunodepresión",
        "actions": "Paquete de sepsis en la primera hora: hemocultivos, antibioterapia de amplio espectro, sueroterapia 30 ml/kg, lactato, vasopresores si persiste la hipotensión tras fluidos.",
        "source": "Surviving Sepsis Campaign (síntesis didáctica)",
    },
    {
        "id": "pediatrico-distres-respiratorio",
        "title": "Distrés respiratorio pediátrico",
        "category": "pediatric",
        "severity": "urgent",
        "symptoms": "Taquipnea, aleteo nasal, tiraje intercostal, quejido espiratorio, sibilancias, cianosis, dificultad para la alimentación",
        "red_flags": "SpO2<92, episodios de apnea, tiraje grave, letargia, deshidratación, lactante <3 meses con fiebre",
        "actions": "Posición de confort. Oxígeno si SpO2<92. Nebulización según protocolo pediátrico. Interconsulta a Pediatría. Monitorización estricta.",
        "source": "Guías de Urgencias Pediátricas (síntesis didáctica)",
    },
    {
        "id": "dolor-abdominal-adulto",
        "title": "Dolor abdominal en el adulto — Triaje diferencial",
        "category": "abdominal",
        "severity": "standard",
        "symptoms": "Dolor abdominal, náuseas, vómitos, diarrea, distensión, anorexia, síntomas urinarios",
        "red_flags": "Abdomen en tabla, dolor intenso desproporcionado a la exploración, hipotensión, melenas, hematemesis, sospecha de embarazo ectópico",
        "actions": "Constantes cada 15 minutos. Vía intravenosa. Analítica: hemograma, lipasa, lactato, perfil lipídico, beta-hCG si procede. Imagen según sospecha clínica.",
        "source": "Vía clínica de dolor abdominal en Urgencias (síntesis didáctica)",
    },
    {
        "id": "anafilaxia-protocolo",
        "title": "Anafilaxia — Manejo urgente",
        "category": "allergy",
        "severity": "critical",
        "symptoms": "Habones generalizados, angioedema, sibilancias, opresión faríngea, hipotensión, vómitos tras alérgeno conocido o sospechoso",
        "red_flags": "Estridor, disfonía, hipotensión, alteración del estado mental, broncoespasmo, afectación multisistémica",
        "actions": "Adrenalina intramuscular 0,3-0,5 mg adulto / 0,01 mg/kg pediátrico. Oxígeno. Sueroterapia. Antihistamínicos. Corticoides. Observación mínima 4-6 horas.",
        "source": "Guías WAO de anafilaxia (síntesis didáctica)",
    },
]


async def main() -> None:
    s = get_settings()
    es = AsyncElasticsearch(hosts=[s.elasticsearch_url], request_timeout=30)
    try:
        # Recreamos el índice para que documentos viejos en inglés no
        # queden cuando se retraduce el corpus. Seguro porque el índice
        # solo guarda protocolos sintetizados, nunca datos de usuario.
        if await es.indices.exists(index=s.elasticsearch_index_protocols):
            await es.indices.delete(index=s.elasticsearch_index_protocols)
            print(f"Deleted existing index {s.elasticsearch_index_protocols}")
        await es.indices.create(index=s.elasticsearch_index_protocols, body=PROTOCOLS_MAPPING)
        print(f"Created index {s.elasticsearch_index_protocols}")
        for p in PROTOCOLS:
            doc_id = p.pop("id")
            await es.index(index=s.elasticsearch_index_protocols, id=doc_id, document=p)
        await es.indices.refresh(index=s.elasticsearch_index_protocols)
        count = (await es.count(index=s.elasticsearch_index_protocols))["count"]
        print(f"Indexed {count} protocols.")
    finally:
        await es.close()


if __name__ == "__main__":
    asyncio.run(main())
