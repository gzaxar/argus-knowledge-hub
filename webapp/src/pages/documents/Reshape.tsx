import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { documentsApi, intakeApi, problemText, reshapeApi, schemasApi, templatesApi } from "../../api/client";
import type { ReshapeResult, ReshapeSource } from "../../api/types";
import { MarkdownEditor } from "../../components/MarkdownEditor";
import { WorkspaceScopeBanner } from "../../components/WorkspaceScopeBanner";

const KINDS: { id: ReshapeSource["kind"]; label: string }[] = [
  { id: "paste", label: "Notes or a transcript" },
  { id: "email", label: "An e-mail" },
  { id: "import", label: "An imported page or file" },
  { id: "intake", label: "From intake" },
];

const SCOPE_LABEL: Record<string, string> = {
  official: "official", workspace: "workspace variant", personal: "your copy", draft: "being edited",
};

/** What the rework hands over when started from elsewhere (intake, a document's page). */
export interface ReshapeSeed {
  text: string;
  kind?: ReshapeSource["kind"];
  filename?: string;
  originalDate?: string;
  subject?: string;
  /** The file the text was read from: attached to the saved draft, so the original is never lost. */
  file?: File;
}

/** Rework raw text — notes, an e-mail, a transcript, an imported page — into a draft that follows the document
 * type's template. The preview saves nothing; saving makes a draft revision that goes through review as usual. */
export function DocumentReshape() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const seed = (location.state as { reshape?: ReshapeSeed } | null)?.reshape;
  const intoDocument = params.get("document");                // a new revision of this one

  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const types = (schemas.data ?? []).filter((s) => s.applies_to === "documents" && s.is_concrete !== false)
    .sort((a, b) => a.name.localeCompare(b.name));

  const [text, setText] = useState(seed?.text ?? "");
  const [kind, setKind] = useState<ReshapeSource["kind"]>(seed?.kind ?? "paste");
  const [filename, setFilename] = useState<string | null>(seed?.filename ?? null);
  const [original, setOriginal] = useState<File | null>(seed?.file ?? null);
  const [attachOriginal, setAttachOriginal] = useState(true);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [originalDate, setOriginalDate] = useState(seed?.originalDate ?? "");
  const [subject, setSubject] = useState(seed?.subject ?? "");
  const [sender, setSender] = useState("");
  const [current, setCurrent] = useState(false);
  const [typeUid, setTypeUid] = useState(params.get("document_type_uid") ?? "");
  const [confidentiality, setConfidentiality] = useState<"pubblico" | "interno" | "riservato">("interno");
  const [templateRef, setTemplateRef] = useState<string>("");     // "": the one that applies
  const typeName = types.find((t) => t.uid === typeUid)?.name;

  const choices = useQuery({ queryKey: ["templates", typeName], queryFn: () => templatesApi.list(typeName),
                             enabled: !!typeName });
  const resolved = useQuery({ queryKey: ["template-resolve", typeName, templateRef],
                              queryFn: () => templatesApi.resolve(typeName!, templateRef || null), enabled: !!typeName });
  useEffect(() => setTemplateRef(""), [typeName]);

  const sourceOf = (): ReshapeSource => ({
    text, kind, filename, original_date: originalDate || null, sender: sender || null, subject: subject || null,
    text_is_current: current,
  });
  const [result, setResult] = useState<ReshapeResult | null>(null);
  const [draft, setDraft] = useState("");
  const [title, setTitle] = useState("");
  const preview = useMutation({
    mutationFn: () => reshapeApi.preview({ source: sourceOf(), document_type_uid: typeUid,
                                           template: templateRef || null, confidentiality, document_uid: intoDocument }),
    onSuccess: (r) => { setResult(r); setDraft(r.markdown); setTitle(r.title); },
  });

  const loadFile = async (file: File) => {
    setFileProblem(null);
    try {
      // Text files as they are; a PDF, Word or Excel file or an e-mail read by the server (nothing kept there).
      const plain = /\.(txt|md|markdown|csv|log)$/i.test(file.name);
      setText(plain ? await file.text() : (await intakeApi.extract(file)).text);
    } catch (e) {
      setFileProblem(problemText(e));
      return;
    }
    setFilename(file.name);
    setOriginal(file);
    setAttachOriginal(true);
    if (/\.(eml|msg)$/i.test(file.name)) setKind("email");
    else if (kind === "paste") setKind("import");
  };

  /** Save the draft, then attach the original file to its revision (the raw text is kept by the server). */
  const saveWithOriginal = async (body: Parameters<typeof reshapeApi.save>[0]) => {
    const saved = await reshapeApi.save(body, intoDocument);
    if (original && attachOriginal) {
      await documentsApi.uploadRevisionAttachment(saved.document_uid, saved.revision_uid, original).catch(() => undefined);
    }
    return saved;
  };

  return (
    <div className="max-w-[1400px] space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Rework from raw text</h1>
          <p className="mt-1 text-sm text-slate-500">
            Notes, an e-mail, a transcript or an imported page, rewritten as a draft that follows the document type's
            template. The preview saves nothing; a saved draft goes through review and approval like any other.
          </p>
        </div>
        <Link to="/documents/templates" className="text-sm text-indigo-600 hover:underline">Templates…</Link>
      </div>
      <WorkspaceScopeBanner action={intoDocument ? "The draft becomes a new revision of a document in" : "The draft will be saved in"} />

      <section className="grid gap-4 rounded-lg border border-slate-200 bg-white p-4 lg:grid-cols-[2fr_1fr]">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="text-sm font-medium text-slate-700">The raw text</label>
            <label className="cursor-pointer text-xs text-indigo-600 hover:underline">
              Open a file (PDF, Word, Excel, e-mail, web page, text)
              <input type="file" accept=".pdf,.docx,.xlsx,.xlsm,.html,.htm,.txt,.md,.markdown,.csv,.eml,text/*" className="hidden"
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) void loadFile(f); e.target.value = ""; }} />
            </label>
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={14} spellCheck={false}
                    placeholder="Paste the notes, the e-mail (with its From / Date / Subject lines), the transcript…"
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs" />
          <p className="text-[11px] text-slate-400">{text.length.toLocaleString()} of 60,000 characters
            {filename ? ` · from ${filename}` : ""}. Instructions written in the text are treated as text.</p>
          {fileProblem && <p className="text-xs text-rose-700">{fileProblem}</p>}
          {original && (
            <label className="mt-1 flex items-center gap-2 text-xs text-slate-700">
              <input type="checkbox" checked={attachOriginal} onChange={(e) => setAttachOriginal(e.target.checked)} />
              Attach the original file, <b>{original.name}</b>, to the saved draft
            </label>
          )}
        </div>
        <div className="space-y-3 text-sm">
          <label className="block">
            <span className="text-slate-700">What it is</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as ReshapeSource["kind"])}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
              {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-slate-700">Written or sent on</span>
            <input type="date" value={originalDate} onChange={(e) => setOriginalDate(e.target.value)}
                   className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5" />
            <span className="text-[11px] text-slate-500">An e-mail's own Date line is read first. "Today", "tomorrow"
              are resolved only from a date like this one.</span>
          </label>
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} className="mt-1" />
            <span className="text-slate-700">The text was written now <span className="block text-[11px] text-slate-500">
              Without a date in it, today's is proposed — you confirm it before saving.</span></span>
          </label>
          {kind === "email" && (
            <div className="grid grid-cols-2 gap-2">
              <input value={sender} onChange={(e) => setSender(e.target.value)} placeholder="From (optional)"
                     className="rounded border border-slate-300 px-2 py-1.5" />
              <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject (optional)"
                     className="rounded border border-slate-300 px-2 py-1.5" />
            </div>
          )}
          <label className="block">
            <span className="text-slate-700">Document type</span>
            <select value={typeUid} onChange={(e) => setTypeUid(e.target.value)}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
              <option value="">Choose…</option>
              {types.map((t) => <option key={t.uid} value={t.uid}>{t.name}</option>)}
            </select>
          </label>
          {typeName && (
            <div className="rounded border border-slate-200 bg-slate-50 p-2">
              <label className="block">
                <span className="text-slate-700">Template</span>
                <select value={templateRef} onChange={(e) => setTemplateRef(e.target.value)}
                        className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
                  <option value="">The one that applies</option>
                  {(choices.data ?? []).filter((c) => c.published).map((c) => (
                    <option key={c.ref} value={c.ref}>{c.name} · v{c.version} · {SCOPE_LABEL[c.scope]}</option>
                  ))}
                </select>
              </label>
              {resolved.data && (
                <p className="mt-1 text-xs text-slate-600">
                  Will use <b>{resolved.data.name}</b> v{resolved.data.version} ({SCOPE_LABEL[resolved.data.scope]}) —{" "}
                  {resolved.data.reason}.
                </p>
              )}
              {resolved.isError && <p className="mt-1 text-xs text-rose-700">{problemText(resolved.error)}</p>}
              <p className="mt-1 text-[11px] text-slate-500">Order: your choice here, then your own copy set as yours,
                then the workspace's variant, then the official template.</p>
            </div>
          )}
          <label className="block">
            <span className="text-slate-700">Confidentiality</span>
            <select value={confidentiality} onChange={(e) => setConfidentiality(e.target.value as typeof confidentiality)}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
              <option value="pubblico">Public</option>
              <option value="interno">Internal</option>
              <option value="riservato">Confidential (riservato)</option>
            </select>
          </label>
          <button type="button" disabled={!text.trim() || !typeUid || preview.isPending} onClick={() => preview.mutate()}
                  className="w-full rounded bg-slate-900 px-4 py-2 font-medium text-white disabled:opacity-40">
            {preview.isPending ? "Reading the text…" : result ? "Preview again" : "Preview"}
          </button>
          {preview.isError && <p className="text-xs text-rose-700">{problemText(preview.error)}</p>}
        </div>
      </section>

      {result && (
        <ReshapeReview result={result} source={text} draft={draft} onDraft={setDraft} title={title} onTitle={setTitle}
                       save={(extra) => saveWithOriginal({
                         source: sourceOf(), document_type_uid: typeUid, template: `${result.template.ref}${
                           result.template.scope === "official" ? "" : `@${result.template.version}`}`,
                         title, markdown: draft, confidentiality, dates: result.dates, extraction: result.extraction,
                         issues: result.issues, model: result.model, ...extra })}
                       onSaved={(uid) => navigate(`/documents/${uid}`)} intoDocument={!!intoDocument} />
      )}
    </div>
  );
}

function ReshapeReview({ result, source, draft, onDraft, title, onTitle, save, onSaved, intoDocument }: {
  result: ReshapeResult; source: string; draft: string; onDraft: (v: string) => void; title: string;
  onTitle: (v: string) => void; save: (extra: Record<string, unknown>) => Promise<{ document_uid: string }>;
  onSaved: (uid: string) => void; intoDocument: boolean;
}) {
  const lines = useMemo(() => source.replace(/\r\n/g, "\n").split("\n"), [source]);
  const cited = useMemo(() => {
    const out = new Set<number>();
    for (const f of Object.values(result.extraction.fields)) f.evidence?.forEach((l) => out.add(l));
    for (const s of Object.values(result.extraction.sections)) s.items.forEach((i) => i.evidence?.forEach((l) => out.add(l)));
    return out;
  }, [result]);
  const uncited = useMemo(() => new Set(result.uncited_lines), [result]);
  const [focus, setFocus] = useState<number | null>(null);
  const sourceBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focus) sourceBox.current?.querySelector(`[data-line="${focus}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  const [confirmDate, setConfirmDate] = useState(false);
  const [code, setCode] = useState("");
  const [links, setLinks] = useState<Set<string>>(new Set());
  const saving = useMutation({
    mutationFn: () => save({ code: code || null, confirm_document_date: confirmDate, link_assets: [...links] }),
    onSuccess: (r) => onSaved(r.document_uid),
  });
  const lineRef = (ls?: number[]) => ls && ls.length > 0 && (
    <button type="button" onClick={() => setFocus(ls[0])} className="ml-1 font-mono text-[11px] text-indigo-600 hover:underline">
      L{ls[0]}{ls.length > 1 ? `–${ls[ls.length - 1]}` : ""}
    </button>
  );
  const d = result.dates;

  return (
    <div className="space-y-4">
      {(result.notices.operational || result.notices.reference) && (
        <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {result.notices.operational ?? result.notices.reference}
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr_1fr]">
        <section className="rounded-lg border border-slate-200 bg-white">
          <h2 className="border-b border-slate-100 px-3 py-2 text-sm font-semibold text-slate-900">Original</h2>
          <p className="px-3 pt-2 text-[11px] text-slate-500">
            <span className="mr-2 inline-block h-2 w-2 rounded-sm bg-emerald-300" />used in the draft
            <span className="ml-3 mr-2 inline-block h-2 w-2 rounded-sm bg-amber-200" />not carried over
          </p>
          <div ref={sourceBox} className="max-h-[70vh] overflow-auto px-1 py-2 font-mono text-[11px] leading-5">
            {lines.map((line, i) => {
              const n = i + 1;
              const tone = n === focus ? "bg-indigo-100" : cited.has(n) ? "bg-emerald-50" : uncited.has(n) ? "bg-amber-50" : "";
              return (
                <div key={n} data-line={n} className={`flex gap-2 px-2 ${tone}`}>
                  <span className="w-8 shrink-0 select-none text-right text-slate-400">{n}</span>
                  <span className="whitespace-pre-wrap break-words text-slate-700">{line || " "}</span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-100 px-3 py-2">
            <h2 className="text-sm font-semibold text-slate-900">Draft</h2>
            <span className="text-[11px] text-slate-500">
              {result.template.name} v{result.template.version} · {SCOPE_LABEL[result.template.scope]} · model {result.model}
            </span>
          </div>
          <div className="p-3">
            <MarkdownEditor value={draft} onChange={onDraft} rows={26} />
            <p className="mt-1 text-[11px] text-slate-500">
              <code>[da confermare]</code>: required and not in the text. <code>[da verificare]</code>: deduced, check it.
              Edit freely; this is what will be saved.
            </p>
          </div>
        </section>

        <section className="space-y-3">
          <Panel title="Dates">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-slate-500">Entered in ARGUS</dt><dd>{new Date(d.inserted_at).toLocaleString()}</dd>
              <dt className="text-slate-500">Original written</dt>
              <dd>{d.source_date ?? "—"}{d.source_date_basis && <span className="text-slate-400"> · {d.source_date_basis}</span>}</dd>
              <dt className="text-slate-500">Event / meeting</dt><dd>{d.event_date ?? "—"}</dd>
              <dt className="text-slate-500">Document</dt>
              <dd className={d.document_date_needs_confirmation ? "font-medium text-amber-800" : ""}>
                {d.document_date ?? "— not known"}{d.document_date_basis && <span className="text-slate-400"> · {d.document_date_basis}</span>}
              </dd>
            </dl>
            {d.document_date_needs_confirmation && (
              <label className="mt-2 flex items-start gap-2 text-xs text-amber-900">
                <input type="checkbox" checked={confirmDate} onChange={(e) => setConfirmDate(e.target.checked)} className="mt-0.5" />
                Yes, {d.document_date} — the day it was entered — is the document's date.
              </label>
            )}
          </Panel>
          <Panel title={`To confirm (${result.missing.length})`}>
            {result.missing.length === 0 ? <Empty /> : (
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-700">{result.missing.map((m) => <li key={m}>{m}</li>)}</ul>
            )}
          </Panel>
          <Panel title={`To check (${result.issues.length + result.ambiguities.length})`}>
            {result.issues.length + result.ambiguities.length === 0 ? <Empty /> : (
              <ul className="space-y-1 text-xs">
                {result.issues.map((i, n) => (
                  <li key={`i${n}`} className={i.kind === "date_conflict" || i.kind === "addressed_to_assistant" ? "text-rose-700" : "text-slate-700"}>
                    {i.where && <b>{i.where}: </b>}{i.message}{lineRef(i.lines)}
                  </li>
                ))}
                {result.ambiguities.map((a, n) => <li key={`a${n}`} className="text-slate-700">{a.text}{lineRef(a.lines)}</li>)}
              </ul>
            )}
            {result.suggested_type && (
              <p className="mt-2 text-xs text-indigo-800">This reads more like a <b>{result.suggested_type}</b>: change the type and preview again if so.</p>
            )}
          </Panel>
          <Panel title="Suggested links">
            {result.links.length === 0 ? <Empty>No record of this workspace is named in the text.</Empty> : (
              <ul className="space-y-1 text-xs">
                {result.links.map((l) => (
                  <li key={`${l.kind}${l.uid}`} className="flex items-start gap-2">
                    {l.kind === "asset" ? (
                      <input type="checkbox" checked={links.has(l.uid)} className="mt-0.5"
                             onChange={(e) => setLinks((s) => { const n = new Set(s); if (e.target.checked) n.add(l.uid); else n.delete(l.uid); return n; })} />
                    ) : <span className="w-3" />}
                    <Link to={`/${l.kind === "asset" ? "assets" : l.kind === "ticket" ? "tickets" : "documents"}/${l.uid}`}
                          target="_blank" className="text-indigo-600 hover:underline">{l.label}</Link>
                    <span className="text-slate-400">{l.kind}</span>
                  </li>
                ))}
                <li className="text-[11px] text-slate-400">Nothing is linked unless ticked; tickets and documents are
                  for reference.</li>
              </ul>
            )}
          </Panel>
          <Panel title={intoDocument ? "Save as a new draft revision" : "Save as a new document"}>
            <div className="space-y-2 text-xs">
              <input value={title} onChange={(e) => onTitle(e.target.value)} placeholder="Title"
                     className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
              {!intoDocument && (
                <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Code (blank: the next one)"
                       className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
              )}
              <button type="button" onClick={() => saving.mutate()}
                      disabled={!title.trim() || saving.isPending || (d.document_date_needs_confirmation && !confirmDate)}
                      className="w-full rounded bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">
                {saving.isPending ? "Saving…" : "Save as draft"}
              </button>
              <p className="text-[11px] text-slate-500">The original text is kept with the revision, with the template and
                its version. Review, approval and publication are the document's usual steps.</p>
              {saving.isError && <p className="text-rose-700">{problemText(saving.error)}</p>}
            </div>
          </Panel>
        </section>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="mb-1.5 text-sm font-semibold text-slate-900">{title}</h3>
      {children}
    </div>
  );
}

function Empty({ children = "Nothing." }: { children?: React.ReactNode }) {
  return <p className="text-xs text-slate-400">{children}</p>;
}
