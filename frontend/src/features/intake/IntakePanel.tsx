"use client";

import { useState } from "react";
import { createTriage, fetchCase, openEventStream } from "@/lib/api";
import { useTriageStore } from "@/store/triageStore";
import { t } from "@/lib/i18n";
import type { TriageIntake } from "@/lib/types";

const PRESETS: { key: keyof typeof t.intake.presets; intake: TriageIntake }[] = [
  {
    key: "respiratory",
    intake: {
      symptoms:
        "Disnea súbita, tos productiva, sibilancias y opresión torácica de 2 horas de evolución.",
      age: 62,
      sex: "male",
      medical_history: "EPOC, hipertensión, ex-fumador (40 paquetes-año).",
      medications: "Tiotropio, salbutamol a demanda, amlodipino.",
      allergies: "Sin alergias conocidas.",
      arrival_mode: "ambulance",
      vital_signs: {
        heart_rate: 118,
        blood_pressure_systolic: 145,
        blood_pressure_diastolic: 90,
        respiratory_rate: 28,
        oxygen_saturation: 89,
        temperature_celsius: 37.4,
        pain_score: 4,
      },
    },
  },
  {
    key: "chestPain",
    intake: {
      symptoms:
        "Dolor torácico opresivo central irradiado a brazo izquierdo desde hace 45 minutos. Sudoración profusa, náuseas.",
      age: 54,
      sex: "male",
      medical_history: "Hipertensión, dislipemia, fumador (20 paquetes-año).",
      medications: "Atorvastatina, ramipril.",
      allergies: "Ninguna.",
      arrival_mode: "walk_in",
      vital_signs: {
        heart_rate: 102,
        blood_pressure_systolic: 158,
        blood_pressure_diastolic: 96,
        respiratory_rate: 22,
        oxygen_saturation: 96,
        temperature_celsius: 36.8,
        pain_score: 8,
      },
    },
  },
  {
    key: "pediatric",
    intake: {
      symptoms: "Fiebre alta de 39,5 °C durante 24 h, irritabilidad, rechazo del alimento, exantema leve.",
      age: 3,
      sex: "female",
      medical_history: "Sano, calendario vacunal al día.",
      medications: "Paracetamol previo.",
      allergies: "Ninguna.",
      arrival_mode: "walk_in",
      vital_signs: {
        heart_rate: 142,
        blood_pressure_systolic: 95,
        blood_pressure_diastolic: 60,
        respiratory_rate: 32,
        oxygen_saturation: 97,
        temperature_celsius: 39.5,
        pain_score: 3,
      },
    },
  },
];

const empty: TriageIntake = {
  symptoms: "",
  age: 0,
  sex: "unknown",
  medical_history: "",
  medications: "",
  allergies: "",
  arrival_mode: "walk_in",
  vital_signs: {},
};

type VitalKey =
  | "heart_rate"
  | "respiratory_rate"
  | "blood_pressure_systolic"
  | "blood_pressure_diastolic"
  | "oxygen_saturation"
  | "temperature_celsius"
  | "pain_score";

const VITAL_RANGES: Record<VitalKey, { min: number; max: number; step?: number }> = {
  heart_rate:               { min: 20, max: 250 },
  respiratory_rate:         { min: 4,  max: 80 },
  blood_pressure_systolic:  { min: 40, max: 260 },
  blood_pressure_diastolic: { min: 20, max: 200 },
  oxygen_saturation:        { min: 50, max: 100, step: 0.1 },
  temperature_celsius:      { min: 28, max: 44,  step: 0.1 },
  pain_score:               { min: 0,  max: 10 },
};

const AGE_RANGE = { min: 0, max: 120 };

const outOfRange = (v: number | null | undefined, r: { min: number; max: number }) =>
  v != null && (v < r.min || v > r.max);

// Catálogo de pistas RAG. Refleja los 9 protocolos poblados en
// Elasticsearch (ver backend/scripts/seed_protocols.py). Se muestra
// inline para que el operador pueda escribir un caso manual que
// aterrice en un protocolo real → agentes coherentes.
const RAG_HINTS: { label: string; keywords: string }[] = [
  { label: "Vía aérea / parada", keywords: "inconsciente, apnea, cianosis, shock, sangrado mayor" },
  { label: "Respiratorio", keywords: "disnea, sibilancias, EPOC, asma, SpO2 bajo" },
  { label: "Cardíaco", keywords: "dolor torácico opresivo, irradiado, sudoración, palpitaciones" },
  { label: "Neurológico", keywords: "hemiparesia, disartria, déficit focal, cefalea súbita" },
  { label: "Sepsis", keywords: "fiebre alta, hipotensión, taquicardia, confusión, foco infeccioso" },
  { label: "Pediátrico", keywords: "lactante, tiraje, fiebre, rechazo del alimento, aleteo nasal" },
  { label: "Abdominal", keywords: "dolor abdominal, vómitos, distensión, melenas" },
  { label: "Anafilaxia", keywords: "urticaria, edema, estridor tras alérgeno" },
];

export function IntakePanel() {
  const [intake, setIntake] = useState<TriageIntake>(empty);
  const [submitting, setSubmitting] = useState(false);
  const [hintsOpen, setHintsOpen] = useState(false);
  const { caseId, running, setCaseId, reset, pushEvent, finish, setReport, setDelivery, setJiraKey } =
    useTriageStore();

  const applyPreset = (p: TriageIntake) => setIntake(p);

  const submit = async () => {
    setSubmitting(true);
    try {
      reset();
      const { case_id } = await createTriage(intake);
      setCaseId(case_id);
      openEventStream(
        case_id,
        (e) => pushEvent(e),
        async () => {
          const final = await fetchCase(case_id);
          setReport(final.report);
          if (final.delivery) setDelivery(final.delivery);
          if (final.jira_key) setJiraKey(final.jira_key);
          finish();
        },
      );
    } catch (err) {
      console.error(err);
      finish();
    } finally {
      setSubmitting(false);
    }
  };

  const upd = (patch: Partial<TriageIntake>) => setIntake({ ...intake, ...patch });
  const updV = (patch: Partial<TriageIntake["vital_signs"]>) =>
    setIntake({ ...intake, vital_signs: { ...intake.vital_signs, ...patch } });

  const v = intake.vital_signs;
  const invalidVitals: VitalKey[] = (Object.keys(VITAL_RANGES) as VitalKey[]).filter((k) =>
    outOfRange(v[k] as number | null | undefined, VITAL_RANGES[k]),
  );
  const ageInvalid = intake.age != null && (intake.age < AGE_RANGE.min || intake.age > AGE_RANGE.max);
  const hasErrors = invalidVitals.length > 0 || ageInvalid;

  return (
    <aside className="w-full h-full border-r border-white/5 bg-bg-panel/70 backdrop-blur-sm flex flex-col">
      <header className="px-5 py-4 border-b border-white/5">
        <div className="text-xs uppercase tracking-widest text-accent-cyan/80">
          {t.intake.sectionTag}
        </div>
        <h1 className="text-lg font-semibold mt-1">{t.intake.title}</h1>
        <p className="text-xs text-white/40 mt-1">{t.intake.safetyHint}</p>
      </header>

      <div className="px-5 py-3 border-b border-white/5">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[10px] uppercase tracking-widest text-white/40">
            {t.intake.presetsLabel}
          </div>
          <button
            onClick={() => setIntake(empty)}
            disabled={running || submitting}
            className="text-[10px] uppercase tracking-widest text-accent-violet/80 hover:text-accent-violet disabled:opacity-30"
            title="Vaciar todos los campos para escribir un caso desde cero"
          >
            Limpiar / caso manual
          </button>
        </div>
        <div className="grid grid-cols-1 gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => applyPreset(p.intake)}
              className="text-left text-xs px-2.5 py-1.5 rounded border border-white/5 bg-white/[0.02] hover:border-accent-cyan/40 hover:bg-accent-cyan/5 transition"
            >
              {t.intake.presets[p.key]}
            </button>
          ))}
        </div>
        <button
          onClick={() => setHintsOpen((v) => !v)}
          className="mt-2 w-full text-left text-[10px] uppercase tracking-widest text-white/45 hover:text-accent-cyan flex items-center justify-between"
          aria-expanded={hintsOpen}
        >
          <span>Categorías reconocidas por el RAG</span>
          <span className="font-mono">{hintsOpen ? "−" : "+"}</span>
        </button>
        {hintsOpen && (
          <ul className="mt-2 space-y-1.5 text-[11px] leading-snug">
            {RAG_HINTS.map((h) => (
              <li key={h.label} className="border border-white/5 rounded px-2 py-1.5 bg-white/[0.02]">
                <div className="text-white/80 font-semibold">{h.label}</div>
                <div className="text-white/45">{h.keywords}</div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 space-y-3 text-sm">
        <Field label={t.intake.fields.symptoms}>
          <textarea
            className="ti-input min-h-[64px]"
            value={intake.symptoms}
            onChange={(e) => upd({ symptoms: e.target.value })}
            placeholder={t.intake.fields.symptomsPh}
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t.intake.fields.age} error={ageInvalid ? `${AGE_RANGE.min}–${AGE_RANGE.max}` : undefined}>
            <input
              type="number"
              min={AGE_RANGE.min}
              max={AGE_RANGE.max}
              className={`ti-input ${ageInvalid ? "ti-input--error" : ""}`}
              value={intake.age || ""}
              onChange={(e) => upd({ age: Number(e.target.value) })}
            />
          </Field>
          <Field label={t.intake.fields.sex}>
            <select
              className="ti-input"
              value={intake.sex}
              onChange={(e) => upd({ sex: e.target.value as TriageIntake["sex"] })}
            >
              <option value="unknown">{t.intake.sex.unknown}</option>
              <option value="male">{t.intake.sex.male}</option>
              <option value="female">{t.intake.sex.female}</option>
              <option value="other">{t.intake.sex.other}</option>
            </select>
          </Field>
        </div>
        <Field label={t.intake.fields.arrival}>
          <select
            className="ti-input"
            value={intake.arrival_mode}
            onChange={(e) => upd({ arrival_mode: e.target.value as TriageIntake["arrival_mode"] })}
          >
            <option value="walk_in">{t.intake.arrival.walk_in}</option>
            <option value="ambulance">{t.intake.arrival.ambulance}</option>
            <option value="transfer">{t.intake.arrival.transfer}</option>
          </select>
        </Field>
        <Field label={t.intake.fields.history}>
          <input
            className="ti-input"
            value={intake.medical_history}
            onChange={(e) => upd({ medical_history: e.target.value })}
          />
        </Field>
        <Field label={t.intake.fields.medications}>
          <input
            className="ti-input"
            value={intake.medications}
            onChange={(e) => upd({ medications: e.target.value })}
          />
        </Field>
        <Field label={t.intake.fields.allergies}>
          <input
            className="ti-input"
            value={intake.allergies}
            onChange={(e) => upd({ allergies: e.target.value })}
          />
        </Field>

        <div className="pt-2 border-t border-white/5">
          <div className="text-[10px] uppercase tracking-widest text-white/40 mb-2">
            {t.intake.fields.vitalsSection}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <VitalField labelText={t.intake.fields.hr}   vkey="heart_rate"               value={v.heart_rate}               onChange={(n) => updV({ heart_rate: n })} />
            <VitalField labelText={t.intake.fields.rr}   vkey="respiratory_rate"         value={v.respiratory_rate}         onChange={(n) => updV({ respiratory_rate: n })} />
            <VitalField labelText={t.intake.fields.sbp}  vkey="blood_pressure_systolic"  value={v.blood_pressure_systolic}  onChange={(n) => updV({ blood_pressure_systolic: n })} />
            <VitalField labelText={t.intake.fields.dbp}  vkey="blood_pressure_diastolic" value={v.blood_pressure_diastolic} onChange={(n) => updV({ blood_pressure_diastolic: n })} />
            <VitalField labelText={t.intake.fields.spo2} vkey="oxygen_saturation"        value={v.oxygen_saturation}        onChange={(n) => updV({ oxygen_saturation: n })} />
            <VitalField labelText={t.intake.fields.temp} vkey="temperature_celsius"      value={v.temperature_celsius}      onChange={(n) => updV({ temperature_celsius: n })} />
            <VitalField labelText={t.intake.fields.pain} vkey="pain_score"               value={v.pain_score}               onChange={(n) => updV({ pain_score: n })} />
          </div>
          {hasErrors && (
            <p className="mt-2 text-[11px] text-red-400/90">
              Hay constantes vitales fuera de rango clínico plausible. Revise los campos resaltados antes de iniciar.
            </p>
          )}
        </div>
      </div>

      <footer className="px-5 py-4 border-t border-white/5 space-y-2">
        <button
          disabled={submitting || running || !intake.symptoms || !intake.age || hasErrors}
          onClick={submit}
          className="w-full rounded bg-accent-cyan/90 text-bg-base font-semibold py-2 text-sm disabled:opacity-40 hover:bg-accent-cyan transition"
        >
          {running ? t.intake.buttons.running : submitting ? t.intake.buttons.starting : t.intake.buttons.start}
        </button>
        {caseId && (
          <div className="text-[10px] text-white/40 font-mono">
            {t.intake.caseLabel}: {caseId}
          </div>
        )}
      </footer>

      <style jsx global>{`
        .ti-input {
          width: 100%;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.07);
          color: #e6ecf5;
          border-radius: 6px;
          padding: 7px 9px;
          font-size: 13px;
          line-height: 1.35;
          outline: none;
        }
        .ti-input:focus { border-color: rgba(54, 208, 255, 0.5); }
        .ti-input--error { border-color: rgba(248, 113, 113, 0.65); background: rgba(248, 113, 113, 0.06); }
        .ti-input--error:focus { border-color: rgba(248, 113, 113, 0.9); }
        html.ti-presentation .ti-input { font-size: 15px; padding: 9px 11px; }
      `}</style>
    </aside>
  );
}

function Field({
  label,
  children,
  error,
}: {
  label: string;
  children: React.ReactNode;
  error?: string;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-widest text-white/55 flex items-center gap-2">
        {label}
        {error && <span className="text-red-400/80 normal-case tracking-normal">· rango {error}</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function VitalField({
  labelText,
  vkey,
  value,
  onChange,
}: {
  labelText: string;
  vkey: VitalKey;
  value: number | null | undefined;
  onChange: (n: number | null) => void;
}) {
  const r = VITAL_RANGES[vkey];
  const invalid = outOfRange(value, r);
  return (
    <Field label={labelText} error={invalid ? `${r.min}–${r.max}` : undefined}>
      <input
        className={`ti-input ${invalid ? "ti-input--error" : ""}`}
        type="number"
        min={r.min}
        max={r.max}
        step={r.step ?? 1}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      />
    </Field>
  );
}
