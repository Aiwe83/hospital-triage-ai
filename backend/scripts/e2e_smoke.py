"""End-to-end smoke test against the running backend (localhost:8000).

Exercises: intake validation, agent workflow, report generation,
Drive delivery, Jira status. Prints a results table.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import httpx

BASE = "http://localhost:8000"
TIMEOUT = 120.0

RESULTS: list[tuple[str, str, str]] = []  # (step, status, detail)


def record(step: str, ok: bool, detail: str) -> None:
    RESULTS.append((step, "PASS" if ok else "FAIL", detail))


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as c:
        # 1. Health
        try:
            r = c.get("/health")
            r.raise_for_status()
            record("health", True, r.json().get("status", "?"))
        except Exception as e:
            record("health", False, str(e))
            return 1

        # 2. Reject invalid intake (temp=60)
        bad_intake = {
            "symptoms": "test invalid case",
            "age": 50,
            "vital_signs": {"temperature_celsius": 60},
        }
        r = c.post("/triage", json=bad_intake)
        if r.status_code == 422:
            errs = r.json().get("detail", [])
            msg = errs[0].get("msg", "") if errs else ""
            record("reject temp=60", True, f"422 ({msg[:50]})")
        else:
            record("reject temp=60", False, f"got {r.status_code}, expected 422")

        # 3. Reject hr=400
        r = c.post(
            "/triage",
            json={"symptoms": "x" * 5, "age": 30, "vital_signs": {"heart_rate": 400}},
        )
        record("reject hr=400", r.status_code == 422, f"status={r.status_code}")

        # 4. Accept valid intake (chest pain preset)
        good_intake = {
            "symptoms": "Dolor torácico opresivo irradiado a brazo izquierdo, sudoración profusa.",
            "age": 54,
            "sex": "male",
            "medical_history": "HTA, dislipemia, fumador.",
            "medications": "Atorvastatina, ramipril.",
            "allergies": "Ninguna.",
            "arrival_mode": "walk_in",
            "vital_signs": {
                "heart_rate": 102,
                "blood_pressure_systolic": 158,
                "blood_pressure_diastolic": 96,
                "respiratory_rate": 22,
                "oxygen_saturation": 96,
                "temperature_celsius": 36.8,
                "pain_score": 8,
            },
        }
        r = c.post("/triage", json=good_intake)
        if r.status_code != 200:
            record("create case", False, f"status={r.status_code} body={r.text[:120]}")
            print_table()
            return 1
        case = r.json()
        case_id = case["case_id"]
        record("create case", True, f"id={case_id[:8]}… status={case['status']}")

        # 5. Poll until completed
        final: dict[str, Any] = {}
        deadline = time.time() + 90
        while time.time() < deadline:
            r = c.get(f"/triage/{case_id}")
            if r.status_code != 200:
                continue
            final = r.json()
            if final.get("status") in ("completed", "error"):
                break
            time.sleep(1.5)
        record(
            "workflow finish",
            final.get("status") == "completed",
            f"status={final.get('status')} trace_len={len(final.get('agent_trace', []))}",
        )

        # 6. Verify report fields
        report = final.get("report") or {}
        report_ok = bool(
            report.get("suggested_priority")
            and report.get("summary")
            and "soporte a la decisión" in report.get("disclaimer", "")
        )
        record(
            "report generated",
            report_ok,
            f"priority={report.get('suggested_priority')} "
            f"risks={len(report.get('risk_factors', []))} "
            f"protocols={len(report.get('retrieved_protocols', []))}",
        )

        # 7. Agent trace covers expected nodes
        trace = final.get("agent_trace", [])
        agent_ids = {ev.get("agent_id") for ev in trace}
        expected = {
            "triage_orchestrator",
            "clinical_analyst",
            "protocol_researcher",
            "hospital_systems_executor",
            "clinical_safety_validator",
            "report_writer",
        }
        missing = expected - agent_ids
        record("all 6 agents fired", not missing, f"missing={sorted(missing) or 'none'}")

        # 8. Drive delivery (mock mode by default)
        r = c.post(f"/triage/{case_id}/deliver")
        if r.status_code != 200:
            record("drive deliver", False, f"status={r.status_code} body={r.text[:120]}")
        else:
            # Wait for delivery completion via case state
            ddeadline = time.time() + 45
            delivery = None
            while time.time() < ddeadline:
                cr = c.get(f"/triage/{case_id}")
                delivery = cr.json().get("delivery")
                if delivery and delivery.get("status") in ("delivered", "error"):
                    break
                time.sleep(1.0)
            ok = bool(delivery and delivery.get("status") == "delivered")
            record(
                "drive deliver",
                ok,
                f"status={delivery.get('status') if delivery else 'none'} "
                f"mode={delivery.get('mode') if delivery else '?'}",
            )

        # 9. Jira status (integration may be disabled)
        r = c.get("/jira/status")
        if r.status_code == 200:
            js = r.json()
            enabled = js.get("enabled")
            jira_key = final.get("jira_key")
            if enabled:
                record("jira integration", bool(jira_key), f"enabled, key={jira_key}")
            else:
                record("jira integration", True, "disabled (feature flag OFF) — expected in mock setup")
        else:
            record("jira integration", False, f"status={r.status_code}")

    print_table()
    failures = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    return 0 if failures == 0 else 1


def print_table() -> None:
    w1 = max(len(s) for s, _, _ in RESULTS)
    w2 = 4
    w3 = max(len(d) for _, _, d in RESULTS)
    print()
    print(f"| {'Step'.ljust(w1)} | {'Res'.ljust(w2)} | {'Detail'.ljust(w3)} |")
    print(f"| {'-'*w1} | {'-'*w2} | {'-'*w3} |")
    for step, status, detail in RESULTS:
        print(f"| {step.ljust(w1)} | {status.ljust(w2)} | {detail.ljust(w3)} |")
    print()


if __name__ == "__main__":
    sys.exit(main())
