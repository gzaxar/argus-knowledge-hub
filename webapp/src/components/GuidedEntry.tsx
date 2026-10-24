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
  onSource,
  describeHint,
}: {
  kind: IntakeKind;
  draft: Draft;
  /** Fill these fields (by guide field name: "name", "attributes.serial"…). */
  onApply: (values: Draft) => void;
  /** The latest assistant result, kept by the form to record the outcome on save. */
  onAssist?: (result: AssistResult) => void;
  /** For a document: the file it starts from (null when removed), for the form to attach as its source. */
  onSource?: (file: File | null) => void;
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
  // A document's file (PDF, Word, Excel, e-mail, text), read whole: its text is the body as it is, or what the
  // template rework starts from — never replaced by the summary the assistant writes of it.
  const [fileText, setFileText] = useState<{ name: string; text: string; truncated: boolean } | null>(null);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  // "Keep it as it is": the suggestions the assistant then makes go into the fields still empty.
  const autoFill = useRef(false);
  const isDocument = kind === "document";

  const debounced = useDebounced(draft, 400);
  const guide = useQuery({
    queryKey: ["intake-guide", kind, JSON.stringify(debounced)],
    queryFn: () => intakeApi.guide(kind, debounced),
    placeholderData: (prev) => prev,
  });

  const assist = useMutation({
    // A file, or — for a document kept as it is — the text read from its file (any kind the body can take).
    mutationFn: (input?: File | { text: string }) =>
      input instanceof File ? intakeApi.assistFile(kind, input, text, draft)
        : intakeApi.assist(kind, input?.text ?? text, draft),
    onSuccess: (r) => {
      setResult(r);
      setUsed(new Set());
      onAssist?.(r);
      if (autoFill.current) {
        autoFill.current = false;
        fillEmpty(r, Object.keys(r.fields).filter((f) => f !== "body_markdown"));
      }
    },
  });

  /** The suggestions of `r` for `fields`, into the fields still empty. */
  const fillEmpty = (r: AssistResult, fields: string[]) => {
    const values: Draft = {};
    for (const f of fields) {
      const current = valueOf(draft, f);
      if (current !== undefined && current !== null && current !== "" && !(Array.isArray(current) && !current.length)) continue;
      values[f] = r.fields[f].value;
    }
    onApply(values);
    setUsed((prev) => new Set([...prev, ...Object.keys(values)]));
  };

  /** What the document starts from: the file's text, or what was pasted. */
  const sourceText = () => fileText?.text ?? text;

  const readFile = async (file: File) => {
    setSourceFile(file);
    onSource?.(file);
    setFileText(null);
    setFileProblem(null);
    setExtracting(true);
    try {
      const out = await intakeApi.extract(file);
      setFileText({ name: file.name, text: out.text, truncated: out.truncated });
    } catch (e) {
      setFileProblem(e instanceof ApiError ? String((e.body as { detail?: string })?.detail ?? e.message) : String(e));
    } finally {
      setExtracting(false);
    }
  };

  const keepAsIs = () => {
    const body = sourceText().trim();
    if (!body) return;
    const now = String(draft.body_markdown ?? "").trim();
    if (now && now !== body && !confirm("Replace what the body says now with this text?")) return;
    onApply({ body_markdown: body });
    if (canAssist) {
      autoFill.current = true;
      assist.mutate(fileText ? { text: fileText.text } : undefined);
    }
  };

  const rework = () => navigate(
    `/documents/reshape${draft.document_type_uid ? `?document_type_uid=${encodeURIComponent(String(draft.document_type_uid))}` : ""}`,
    { state: { reshape: { text: sourceText(), kind: fileText ? "import" : "intake", filename: fileText?.name,
                          file: sourceFile ?? undefined } } });

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
        {isDocument ? (
          <>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="Paste the document's text, or add its file (PDF, Word, Excel, e-mail, web page, text)."
              className="mt-2 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={!canAssist || extracting || !(text.trim() || fileText)}
                onClick={rework}
                className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                title={canAssist ? "The whole text rewritten as a draft that follows the type's template, with what to check"
                                  : "Needs the assistant"}
              >
                Rework with the template
              </button>
              <button
                type="button"
                disabled={extracting || assist.isPending || !(text.trim() || fileText)}
                onClick={keepAsIs}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
                title="The text becomes the body as it is"
              >
                {assist.isPending ? "Suggesting the title…" : "Keep it as it is"}
              </button>
              <button
                type="button"
                disabled={extracting}
                onClick={() => photo.current?.click()}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >
                {sourceFile ? "Another file" : "Add a file"}
              </button>
              <input
                ref={photo}
                type="file"
                accept=".pdf,.docx,.xlsx,.xlsm,.eml,.html,.htm,.txt,.md,.markdown,.csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void readFile(file);
                }}
              />
            </div>
            <p className="mt-1 text-[11px] text-slate-500">
              <b>Rework with the template</b>: a whole draft that follows the type&apos;s template, with what to check.{" "}
              <b>Keep it as it is</b>: the text becomes the body, in Markdown with the file&apos;s headings, lists and
              tables
              {canAssist ? "; title, type, keywords and a summary are suggested" : ""}. A file you add is attached to
              the document either way — the original is never lost.
            </p>
            {extracting && <p className="mt-2 text-xs text-slate-500">Reading {sourceFile?.name}…</p>}
            {sourceFile && !extracting && (
              <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-indigo-200 bg-indigo-50 px-2 py-1.5 text-xs text-indigo-900">
                <span className="min-w-0 flex-1">
                  <b>{sourceFile.name}</b>
                  {fileText
                    ? ` · ${fileText.text.length.toLocaleString()} characters read${fileText.truncated ? " (only the first 60,000)" : ""}`
                    : ""}
                  {" "}· attached to the document when it is saved
                </span>
                <button
                  type="button"
                  onClick={() => { setSourceFile(null); setFileText(null); setFileProblem(null); onSource?.(null); }}
                  className="shrink-0 rounded border border-indigo-300 px-2 py-0.5 hover:bg-white"
                >
                  Remove
                </button>
              </div>
            )}
            {fileProblem && (
              <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
                {fileProblem} The file is still attached to the document; type or paste its text to use it.
              </p>
            )}
            {canAssist && profiles.isSuccess && !profile && (
              <p className="mt-1 text-[11px] text-slate-400">
                The model in use here has not been evaluated on the golden dataset yet: check every suggestion.
              </p>
            )}
          </>
        ) : canAssist ? (
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
                  assist.mutate(file);
                }}
              />
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
