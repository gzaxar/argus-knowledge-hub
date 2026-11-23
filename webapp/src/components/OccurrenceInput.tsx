import { useState } from "react";

/** When something happened, with the precision the person actually knows
 * (asset-model-revision §8.2, D8): an exact time, a day, or a month. The
 * value is the temporal value the ticket stores as `occurred_from`. */
type Precision = "instant" | "day" | "month";
export type TemporalValue = { kind: "date"; nominal: string; precision: Precision };

function toInput(v: TemporalValue | null | undefined): string {
  if (!v?.nominal) return "";
  if (v.precision === "month") return v.nominal.slice(0, 7);
  if (v.precision === "day") return v.nominal.slice(0, 10);
  const d = new Date(v.nominal);
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromInput(raw: string, precision: Precision): TemporalValue | null {
  if (!raw) return null;
  if (precision === "month") return { kind: "date", nominal: `${raw}-01T00:00:00+00:00`, precision };
  if (precision === "day") return { kind: "date", nominal: `${raw}T00:00:00+00:00`, precision };
  return { kind: "date", nominal: new Date(raw).toISOString(), precision };
}

export function OccurrenceInput({
  value,
  onChange,
  required,
}: {
  value: TemporalValue | null | undefined;
  onChange: (v: TemporalValue | null) => void;
  required?: boolean;
}) {
  const [chosen, setChosen] = useState<Precision>(value?.precision ?? "day");
  const precision: Precision = value?.precision ?? chosen;
  const type = precision === "instant" ? "datetime-local" : precision === "day" ? "date" : "month";

  const changePrecision = (p: Precision) => {
    setChosen(p);
    if (!value) return;
    // Keep what is known: coarser drops the detail, finer starts at the known start.
    const start = value.nominal;
    if (p === "month") onChange(fromInput(start.slice(0, 7), "month"));
    else if (p === "day") onChange(fromInput(start.slice(0, 10), "day"));
    else onChange({ kind: "date", nominal: start, precision: "instant" });
  };

  return (
    <div>
      <label className="block text-sm font-medium text-slate-700">
        When did it happen?{required && <span className="text-red-500"> *</span>}
      </label>
      <div className="mt-1 flex gap-2">
        <select
          value={precision}
          onChange={(e) => changePrecision(e.target.value as Precision)}
          className="rounded border border-slate-300 px-2 py-2 text-sm"
          aria-label="How precisely you know it"
        >
          <option value="instant">at an exact time</option>
          <option value="day">on a day</option>
          <option value="month">in a month</option>
        </select>
        <input
          aria-label="When it happened"
          type={type}
          value={toInput(value)}
          required={required}
          onChange={(e) => onChange(fromInput(e.target.value, precision))}
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <p className="mt-1 text-xs text-slate-500">The day is enough if you do not know the time.</p>
    </div>
  );
}
