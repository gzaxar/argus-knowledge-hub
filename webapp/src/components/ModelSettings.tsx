import { useState } from "react";
import type { ModelSetting, ModelTestResult } from "../api/types";

export const DEFAULT_SETTING: ModelSetting = { temperature: null, no_thinking: true, json_mode: true, time_limit_s: null };

/** How each model is called, by its name ("auto" included): its temperature, whether it is told not to think,
 *  JSON mode, and how long a structured answer may take — each row tried with Test on a small extraction. */
export function ModelSettingsEditor({ rows, onChange, suggestions, test }: {
  rows: Record<string, ModelSetting>;
  onChange: (rows: Record<string, ModelSetting>) => void;
  /** The model names these settings use, offered to add. */
  suggestions: string[];
  test: (model: string, settings: ModelSetting) => Promise<ModelTestResult>;
}) {
  const [adding, setAdding] = useState("");
  const [results, setResults] = useState<Record<string, ModelTestResult | "running" | string>>({});
  const names = Object.keys(rows);
  const set = (name: string, patch: Partial<ModelSetting>) => onChange({ ...rows, [name]: { ...rows[name], ...patch } });
  const add = (name: string) => {
    const n = name.trim();
    if (n && !rows[n]) onChange({ ...rows, [n]: { ...DEFAULT_SETTING } });
    setAdding("");
  };
  const remove = (name: string) => {
    const next = { ...rows };
    delete next[name];
    onChange(next);
  };
  const run = (name: string) => {
    setResults((r) => ({ ...r, [name]: "running" }));
    test(name, rows[name])
      .then((out) => setResults((r) => ({ ...r, [name]: out })))
      .catch((e) => setResults((r) => ({ ...r, [name]: e instanceof Error ? e.message : "The test could not run." })));
  };
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const missing = suggestions.filter((s) => s && !rows[s]);
  return (
    <div className="space-y-2">
      {names.length === 0 && <p className="text-xs text-slate-500">No model has settings of its own: ARGUS's defaults apply.</p>}
      {names.map((name) => {
        const s = rows[name];
        const r = results[name];
        return (
          <div key={name} className="rounded border border-slate-200 p-2 text-sm">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="font-mono font-medium text-slate-800">{name}</span>
              <label className="flex items-center gap-1 text-xs text-slate-600">
                Temperature
                <input type="number" min={0} max={2} step={0.1} value={s.temperature ?? ""} placeholder="default"
                       aria-label={`Temperature of ${name}`}
                       onChange={(e) => set(name, { temperature: num(e.target.value) })}
                       className="w-20 rounded border border-slate-300 px-2 py-0.5" />
              </label>
              <label className="flex items-center gap-1 text-xs text-slate-600">
                <input type="checkbox" checked={s.no_thinking} onChange={(e) => set(name, { no_thinking: e.target.checked })} />
                Tell it not to think
              </label>
              <label className="flex items-center gap-1 text-xs text-slate-600">
                <input type="checkbox" checked={s.json_mode} onChange={(e) => set(name, { json_mode: e.target.checked })} />
                JSON mode
              </label>
              <label className="flex items-center gap-1 text-xs text-slate-600">
                Time limit
                <input type="number" min={10} max={3600} step={10} value={s.time_limit_s ?? ""} placeholder="280"
                       aria-label={`Time limit of ${name}`}
                       onChange={(e) => set(name, { time_limit_s: num(e.target.value) })}
                       className="w-20 rounded border border-slate-300 px-2 py-0.5" /> s
              </label>
              <span className="ml-auto flex gap-2">
                <button type="button" onClick={() => run(name)} disabled={r === "running"}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50">
                  {r === "running" ? "Testing…" : "Test"}
                </button>
                <button type="button" onClick={() => remove(name)} className="text-xs text-red-600 underline">remove</button>
              </span>
            </div>
            {r && r !== "running" && (
              <p role="status" className={`mt-1 text-xs ${typeof r === "string" || !r.ok ? "text-red-700" : "text-emerald-800"}`}>
                {typeof r === "string" ? r
                  : r.ok ? `Answered with the JSON in ${r.seconds} s${r.answered_by && r.answered_by !== name ? `, by ${r.answered_by}` : ""}.`
                  : `${r.error ?? "No usable answer"} (${r.seconds} s${r.answered_by ? `, ${r.answered_by}` : ""}).`}
              </p>
            )}
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="A model's name, e.g. minimax-m27"
               aria-label="Model to add" className="w-64 rounded border border-slate-300 px-2 py-1" />
        <button type="button" onClick={() => add(adding)} disabled={!adding.trim()}
                className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-40">Add</button>
        {missing.map((m) => (
          <button key={m} type="button" onClick={() => add(m)} className="text-indigo-700 underline">add {m}</button>
        ))}
      </div>
    </div>
  );
}
