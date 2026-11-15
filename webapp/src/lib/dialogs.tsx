/**
 * The app's own questions and notices, in place of the browser's alert, confirm and prompt: those freeze the
 * page, cannot be styled or tested, and look like they come from somewhere else.
 *
 *   notify("Saved.")                         a notice that goes away by itself (an error stays until dismissed)
 *   if (await ask("Delete it?")) …           a yes/no question
 *   const why = await askText("Why?")        a question with an answer; null when cancelled
 *   if (await askTyped("Delete it?", name)) … a dangerous action, confirmed twice: yes, then the name typed
 *
 * <DialogHost /> is mounted once, at the root.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

type Notice = { id: number; text: string; kind: "info" | "error" };
type Question = { id: number; text: string; input: boolean; initial: string; danger: boolean; mustType?: string;
                  resolve: (v: string | boolean | null) => void };

let notices: Notice[] = [];
let question: Question | null = null;
const waiting: Question[] = [];
let seq = 0;
const listeners = new Set<() => void>();
let snapshot: { notices: Notice[]; question: Question | null } = { notices, question };
const changed = () => { snapshot = { notices, question }; listeners.forEach((l) => l()); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** Words that say a message is a failure, so it is shown as one and stays. */
const FAILURE = /fail|could not|cannot|error|refus|not allowed|denied/i;

export function notify(text: string, kind?: "info" | "error"): void {
  const n: Notice = { id: ++seq, text: String(text), kind: kind ?? (FAILURE.test(String(text)) ? "error" : "info") };
  notices = [...notices, n];
  changed();
  if (n.kind === "info") setTimeout(() => dismiss(n.id), 5000);
}

function dismiss(id: number) {
  notices = notices.filter((n) => n.id !== id);
  changed();
}

function put(q: Omit<Question, "id">) {
  const full = { ...q, id: ++seq };
  if (question) waiting.push(full); else question = full;
  changed();
}

function answer(value: string | boolean | null) {
  const q = question;
  question = waiting.shift() ?? null;
  changed();
  q?.resolve(value);
}

/** A destructive question is asked in red: it deletes, removes, revokes or cannot be undone. */
const DANGER = /delete|remove|revoke|retire|cannot be undone|permanently|take .* (out|away|off)/i;

export function ask(text: string): Promise<boolean> {
  return new Promise((resolve) => put({ text, input: false, initial: "", danger: DANGER.test(text),
                                        resolve: (v) => resolve(v === true) }));
}

export function askText(text: string, initial = ""): Promise<string | null> {
  return new Promise((resolve) => put({ text, input: true, initial, danger: false,
                                        resolve: (v) => resolve(typeof v === "string" ? v : null) }));
}

/** A dangerous action (docs/dangerous-actions.md), asked twice: the question, then `name` typed exactly. The
 *  server checks the name again, so it is sent with the request (`confirmHeader`). */
export async function askTyped(text: string, name: string): Promise<boolean> {
  if (!await ask(text)) return false;
  const typed = await new Promise<string | null>((resolve) => put({
    text: `To confirm, type the workspace's name:\n${name}`, input: true, initial: "", danger: true, mustType: name,
    resolve: (v) => resolve(typeof v === "string" ? v : null) }));
  return typed !== null && typed.trim() === name.trim();
}

export function DialogHost() {
  const state = useSyncExternalStore(subscribe, () => snapshot);
  const q = state.question;
  const [text, setText] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);
  const yes = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!q) return;
    setText(q.initial);
    // The answer is where the keyboard is: the field, or the button that says yes.
    setTimeout(() => (q.input ? field.current : yes.current)?.focus(), 0);
  }, [q?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {q && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
             onKeyDown={(e) => { if (e.key === "Escape") answer(q.input ? null : false); }}>
          <div role="dialog" aria-modal="true" aria-label={q.text}
               className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
            <p className="whitespace-pre-wrap break-words text-sm text-slate-800">{q.text}</p>
            {q.input && (
              <textarea ref={field} value={text} onChange={(e) => setText(e.target.value)} rows={2}
                        aria-label={q.mustType !== undefined ? "The workspace's name" : undefined}
                        onKeyDown={(e) => {
                          if (e.key !== "Enter" || e.shiftKey) return;
                          e.preventDefault();
                          if (q.mustType === undefined || text.trim() === q.mustType.trim()) answer(text);
                        }}
                        className="mt-3 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => answer(q.input ? null : false)}
                      className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Cancel</button>
              <button type="button" ref={yes} onClick={() => answer(q.input ? text : true)}
                      disabled={q.mustType !== undefined && text.trim() !== q.mustType.trim()}
                      className={`rounded px-3 py-1.5 text-sm text-white disabled:opacity-40 ${q.danger ? "bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800"}`}>
                {q.mustType !== undefined ? "I understand, do it" : q.input ? "OK" : q.danger ? "Yes, go ahead" : "OK"}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[101] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {state.notices.map((n) => (
          <div key={n.id} role={n.kind === "error" ? "alert" : "status"}
               className={`pointer-events-auto flex items-start gap-2 rounded border px-3 py-2 text-sm shadow ${
                 n.kind === "error" ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-white text-slate-800"}`}>
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{n.text}</span>
            <button type="button" onClick={() => dismiss(n.id)} aria-label="Dismiss" className="text-slate-400 hover:text-slate-700">×</button>
          </div>
        ))}
      </div>
    </>
  );
}
