import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  aiApi,
  ApiError,
  intakeApi,
  type AssistResult,
  type GuideCheck,
  type IntakeKind,
  type IntakeSuggestion,
} from "../api/client";

/** Guided entry (asset-model-revision §23): a checklist that keeps an entry
 * correct, and an assistant that fills the form from a description.
 *
 * The checklist needs no model: it runs as the person types and says what is
 * missing, what already exists, and what to answer next. The assistant only
 * suggests. Each suggestion shows where it was read and how sure the reading
 * is, and nothing reaches the form until the person uses it. */

type Draft = Record<string, unknown>;

const PLACEHOLDER: Record<IntakeKind, string> = {
  asset:
    "Describe it in your own words, e.g. “Agilent VacIon Plus 75 ion pump, serial 77120, in the gun area, rack B12.” Or add a photo of its nameplate.",
  ticket:
    "Say what happened, as you would tell a colleague: what you saw, where, when, and what you already tried.",
  document:
    "Describe the document, or paste its text: what it is for, what it covers, who it is for.",
};

const LEVEL_STYLE: Record<string, string> = {
  error: "border-red-200 bg-red-50 text-red-800",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-slate-200 bg-slate-50 text-slate-700",
  ok: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

function fieldName(field: string): string {
  const name = (field.startsWith("attributes.") ? field.slice(11) : field).replace(/^argus_/, "");
  return (
    {
      schema_uid: "type",
      document_type_uid: "document type",
      asset_uid: "affected record",
      body_markdown: "content",
      occurred_from: "when it happened",
    }[name] ?? name.replace(/_/g, " ")
  );
}

function shown(s: IntakeSuggestion): string {
  if (s.label) return s.label;
  if (Array.isArray(s.value)) return s.value.join(", ");
  if (s.value && typeof s.value === "object") {
    const v = s.value as { nominal?: string; precision?: string };
    if (v.nominal) {
      const d = new Date(v.nominal);
      if (v.precision === "month") return d.toLocaleDateString(undefined, { year: "numeric", month: "long" });
      if (v.precision === "day") return d.toLocaleDateString();
      return d.toLocaleString();
    }
  }
  const text = String(s.value ?? "");
  return text.length > 90 ? `${text.slice(0, 90)}…` : text;
}

/** The value the form holds for a field, read the same way the guide names it. */
export function valueOf(draft: Draft, field: string): unknown {
  if (field.startsWith("attributes.")) return ((draft.attributes as Draft) ?? {})[field.slice(11)];
  return draft[field];
}

/** What the person finally saved, for each field the assistant suggested. */
export function finalFor(result: AssistResult | null, draft: Draft): Draft {
  const out: Draft = {};
  for (const field of Object.keys(result?.fields ?? {})) out[field] = valueOf(draft, field) ?? null;
  return out;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function GuidedEntry({
  kind,
  draft,
  onApply,
  onAssist,
  describeHint,
}: {
  kind: IntakeKind;
  draft: Draft;
  /** Fill these fields (by guide field name: "name", "attributes.serial"…). */
  onApply: (values: Draft) => void;
  /** The latest assistant result, kept by the form to record the outcome on save. */
  onAssist?: (result: AssistResult) => void;
  describeHint?: string;
}) {
  const status = useQuery({ queryKey: ["ai-status"], queryFn: aiApi.status, staleTime: 60_000 });
  const ai = status.data;
  const canAssist = !!ai?.validated;
  const canSee = canAssist && kind === "asset" && !!ai?.has_vision;
  const profiles = useQuery({ queryKey: ["intake-status"], queryFn: intakeApi.status, enabled: canAssist, staleTime: 60_000 });
  const profile = profiles.data?.[kind];
  const accept = (canSee ? "image/*," : "") + ".pdf,.docx,.xlsx,.xlsm,.eml,.txt,.md,.csv";

  const [text, setText] = useState("");
  const navigate = useNavigate();
  const [result, setResult] = useState<AssistResult | null>(null);
  const [used, setUsed] = useState<Set<string>>(new Set());
  const photo = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  // A Markdown or text file given for a document: its words can be the body
  // itself, rather than the summary the assistant writes of them.
  const [fileText, setFileText] = useState<{ name: string; text: string; used: boolean } | null>(null);

  const debounced = useDebounced(draft, 400);
  const guide = useQuery({
    queryKey: ["intake-guide", kind, JSON.stringify(debounced)],
    queryFn: () => intakeApi.guide(kind, debounced),
    placeholderData: (prev) => prev,
  });

  const assist = useMutation({
    mutationFn: (file?: File) =>
      file ? intakeApi.assistFile(kind, file, text, draft) : intakeApi.assist(kind, text, draft),
    onSuccess: (r) => {
      setResult(r);
      setUsed(new Set());
      onAssist?.(r);
    },
  });

  const use = (fields: string[]) => {
    if (!result) return;
    const values: Draft = {};
    for (const f of fields) {
      const current = valueOf(draft, f);
      // Never over what the person already typed, unless they choose that one.
      if (fields.length > 1 && current !== undefined && current !== null && current !== "") continue;
      values[f] = result.fields[f].value;
    }
    onApply(values);
    setUsed((prev) => new Set([...prev, ...Object.keys(values)]));
  };

  const fix = (check: GuideCheck, option?: unknown) => {
    if (!check.fix) return;
    const value =
      option === undefined
        ? check.fix.value
        : typeof option === "object" && option !== null && "uid" in option
          ? (option as { uid: string }).uid
          : option;
    onApply({ [check.fix.field]: value });
  };

  const g = guide.data;
  const suggestions = Object.entries(result?.fields ?? {});

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800">Describe it</h2>
          {!canAssist && status.isSuccess && (
            <span className="text-[11px] text-slate-400" title={ai?.reason ?? undefined}>
              assistant unavailable — the checklist still works
            </span>
          )}
        </div>
        {canAssist ? (
          <>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder={describeHint ?? PLACEHOLDER[kind]}
              className="mt-2 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                disabled={assist.isPending || !text.trim()}
                onClick={() => assist.mutate(undefined)}
                className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
              >
                {assist.isPending ? "Reading…" : "Fill the form"}
              </button>
              <button
                type="button"
                disabled={assist.isPending}
                onClick={() => photo.current?.click()}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
                title={canSee ? "A nameplate photo, a datasheet, a Word or Excel file, an email" : "A datasheet, a Word or Excel file, an email"}
              >
                {canSee ? "Add a photo or file" : "Add a file"}
              </button>
              <input
                ref={photo}
                type="file"
                accept={accept}
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  setPreview(file.type.startsWith("image/") ? URL.createObjectURL(file) : null);
                  setFileText(null);
                  if (kind === "document" && /\.(md|markdown|txt)$/i.test(file.name)) {
                    file.text().then((t) => setFileText({ name: file.name, text: t.replace(/\r\n/g, "\n").trim(), used: false }));
                  }
                  assist.mutate(file);
                }}
              />
              {kind === "document" && (
                <button
                  type="button"
                  disabled={!(text.trim() || fileText)}
                  onClick={() => navigate(
                    `/documents/reshape${draft.document_type_uid ? `?document_type_uid=${encodeURIComponent(String(draft.document_type_uid))}` : ""}`,
                    { state: { reshape: { text: fileText?.text ?? text, kind: fileText ? "import" : "intake",
                                          filename: fileText?.name } } })}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
                  title="Rewrite this text as a whole draft that follows the type's template, with what to check"
                >
                  Rework with the template
                </button>
              )}
              <span className="text-[11px] text-slate-400">suggestions only — you decide what is saved</span>
            </div>
            {profiles.isSuccess && (
              <p className="mt-1 text-[11px] text-slate-400">
                {profile
                  ? `Model ${profile.model}, evaluated on the golden dataset${profile.exception ? " (activated with an exception)" : ""}.`
                  : "The model in use here has not been evaluated on the golden dataset yet: check every suggestion."}
              </p>
            )}
          </>
        ) : (
          <p className="mt-1 text-xs text-slate-500">
            Fill in the form; the checklist below tells you what is missing and what already exists.
          </p>
        )}
        {fileText && (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-indigo-200 bg-indigo-50 px-2 py-1.5 text-xs text-indigo-900">
            <span className="min-w-0 flex-1">
              Put the whole of <b>{fileText.name}</b> in the body, instead of a summary of it?
            </span>
            <button
              type="button"
              onClick={() => {
                if (draft.body_markdown && String(draft.body_markdown).trim()
                    && !confirm("Replace what the body says now with the file's text?")) return;
                onApply({ body_markdown: fileText.text });
                setFileText({ ...fileText, used: true });
              }}
              className="shrink-0 rounded bg-slate-900 px-2 py-1 font-medium text-white hover:bg-slate-800"
            >
              {fileText.used ? "In the body" : "Use the file as the body"}
            </button>
          </div>
        )}
        {assist.isError && (
          <p className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {(assist.error instanceof ApiError && assist.error.detail) || (assist.error as Error).message}
          </p>
        )}
        {result && (
          <div className="mt-3 space-y-2">
            {preview && <img src={preview} alt="" className="h-20 rounded border border-slate-200 object-cover" />}
            {result.message && <p className="text-xs text-slate-600">{result.message}</p>}
            {!!result.redacted && (
              <p className="text-[11px] text-slate-500">
                {result.redacted} password or key removed before anything was sent.
              </p>
            )}
            {suggestions.length > 0 && (
              <>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-slate-700">Suggested</p>
                  <button
                    type="button"
                    onClick={() => use(suggestions.map(([f]) => f))}
                    className="text-xs text-indigo-700 hover:underline"
                  >
                    Use all in empty fields
                  </button>
                </div>
                <ul className="divide-y divide-slate-100 rounded border border-slate-200 text-xs">
                  {suggestions.map(([f, s]) => (
                    <li key={f} className="flex items-start gap-2 px-2 py-1.5">
                      <div className="min-w-0 flex-1">
                        <div>
                          <span className="text-slate-500">{fieldName(f)}: </span>
                          <span className="font-medium text-slate-900">{shown(s)}</span>
                          {s.method === "person" && <span className="ml-1 text-[10px] text-slate-400">your words</span>}
                          {s.method === "draft" && <span className="ml-1 text-[10px] text-slate-400">written for you — edit it</span>}
                          {s.confidence !== null && (
                            <span
                              className={`ml-1 rounded px-1 text-[10px] ${
                                s.confidence >= 0.8
                                  ? "bg-emerald-50 text-emerald-700"
                                  : s.confidence >= 0.5
                                    ? "bg-amber-50 text-amber-700"
                                    : "bg-slate-100 text-slate-500"
                              }`}
                            >
                              {Math.round(s.confidence * 100)}%
                            </span>
                          )}
                        </div>
                        {s.evidence && (
                          <div className="truncate text-[11px] text-slate-500">
                            {s.grounded ? `from “${s.evidence}”` : "could not point to where it read this — check it"}
                          </div>
                        )}
                        {!s.evidence && !s.grounded && (
                          <div className="text-[11px] text-slate-500">no evidence given — check it</div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => use([f])}
                        className="shrink-0 rounded border border-slate-300 px-2 py-0.5 text-[11px] hover:bg-slate-50"
                      >
                        {used.has(f) ? "Used" : "Use"}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {result.hypotheses.length > 0 && (
              <div className="rounded border border-violet-200 bg-violet-50 px-2 py-1.5 text-xs text-violet-900">
                <p className="font-medium">Possible causes — unresolved hypotheses, not findings</p>
                <ul className="mt-0.5 list-disc pl-4">
                  {result.hypotheses.map((h) => (
                    <li key={h.text}>{h.text}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.dropped.length > 0 && (
              <details className="text-[11px] text-slate-500">
                <summary>{result.dropped.length} reading(s) not used</summary>
                <ul className="mt-1 space-y-0.5">
                  {result.dropped.map((d, i) => (
                    <li key={i}>
                      {fieldName(d.field)}: {d.reason}
                      {d.link && (
                        <>
                          {" "}
                          <Link to={d.link.path} className="text-indigo-700 hover:underline">
                            open it
                          </Link>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800">Checklist</h2>
          {g && (
            <span
              className={`rounded px-1.5 py-0.5 text-[11px] ${
                g.ready ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
              }`}
            >
              {g.ready ? "ready to save" : "not ready yet"}
            </span>
          )}
        </div>
        {g && (
          <>
            <ol className="mt-2 flex flex-wrap gap-1.5">
              {g.steps.map((s) => (
                <li
                  key={s.id}
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    s.done ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {s.done ? "✓ " : ""}
                  {s.label}
                </li>
              ))}
            </ol>
            {g.next && (
              <p className="mt-2 rounded border border-indigo-200 bg-indigo-50 px-2 py-1.5 text-xs text-indigo-900">
                <span className="font-medium">Next: </span>
                {g.next.question}
              </p>
            )}
            <ul className="mt-2 space-y-1.5">
              {g.checks.map((c) => (
                <li key={c.id + c.message} className={`rounded border px-2 py-1.5 text-xs ${LEVEL_STYLE[c.level]}`}>
                  <p>{c.message}</p>
                  {c.links && c.links.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {c.links.map((l) => (
                        <li key={l.uid} className="flex items-center gap-2">
                          <Link to={l.path} target="_blank" className="text-indigo-700 hover:underline">
                            {l.key} · {l.name}
                          </Link>
                          {c.fix?.field === "asset_uid" && (
                            <button
                              type="button"
                              onClick={() => onApply({ asset_uid: l.uid })}
                              className="rounded border border-current px-1 text-[10px]"
                            >
                              this one
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {c.fix && c.fix.field !== "asset_uid" && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {c.fix.options
                        ? c.fix.options.map((o) => (
                            <button
                              key={typeof o === "string" ? o : o.uid}
                              type="button"
                              onClick={() => fix(c, o)}
                              className="rounded border border-current px-1.5 text-[11px]"
                            >
                              {typeof o === "string" ? o : o.name}
                            </button>
                          ))
                        : c.fix.value !== undefined && (
                            <button
                              type="button"
                              onClick={() => fix(c)}
                              className="rounded border border-current px-1.5 text-[11px]"
                            >
                              use {String(c.fix.value)}
                            </button>
                          )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
