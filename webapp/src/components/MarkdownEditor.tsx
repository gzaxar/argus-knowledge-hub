import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import { MarkdownView } from "./MarkdownView";

type Mode = "write" | "split" | "preview";

interface Upload {
  url: string;
  filename: string;
  isImage: boolean;
}

/** Wraps the selection, or drops a placeholder if there isn't one. */
interface Action {
  label: string;
  title: string;
  /** What goes before and after the selected text. */
  wrap?: [string, string];
  /** What each selected line is prefixed with (lists, quotes, headings). */
  linePrefix?: string;
  /** Inserted whole, for things with no natural selection (tables). */
  block?: string;
  placeholder?: string;
  mono?: boolean;
}

const ACTIONS: Action[][] = [
  [
    { label: "B", title: "Bold", wrap: ["**", "**"], placeholder: "bold" },
    { label: "I", title: "Italic", wrap: ["*", "*"], placeholder: "italic" },
    { label: "`", title: "Inline code", wrap: ["`", "`"], placeholder: "code", mono: true },
  ],
  [
    { label: "H1", title: "Heading 1", linePrefix: "# " },
    { label: "H2", title: "Heading 2", linePrefix: "## " },
    { label: "H3", title: "Heading 3", linePrefix: "### " },
  ],
  [
    { label: "•", title: "Bullet list", linePrefix: "- " },
    { label: "1.", title: "Numbered list", linePrefix: "1. " },
    { label: "☑", title: "Task list", linePrefix: "- [ ] " },
    { label: "❝", title: "Quote / warning panel", linePrefix: "> " },
  ],
  [
    { label: "</>", title: "Code block", wrap: ["```\n", "\n```"], placeholder: "caget BTF:PRESSURE" },
    { label: "🔗", title: "Link", wrap: ["[", "](https://)"], placeholder: "text" },
    {
      label: "▦",
      title: "Table",
      block:
        "\n| Parameter | Value |\n| --- | --- |\n| Pressure | 1e-9 mbar |\n| Current | 180 A |\n",
    },
  ],
];

/** A Markdown editor with the formatting people actually reach for, a live
 * preview of exactly what the document will look like, and files that
 * arrive by paste or drop.
 *
 * Markdown stays the stored form — it is what the importer produces and
 * what a diff between two revisions has to be readable in — so this
 * assists with the syntax rather than hiding it behind a WYSIWYG whose
 * round-trip would quietly rewrite every imported page.
 */
/** Markdown or plain text: something whose words can be the body itself. */
function isTextDocument(file: File): boolean {
  return /\.(md|markdown|txt)$/i.test(file.name) || file.type === "text/markdown";
}

export function MarkdownEditor({
  value,
  onChange,
  onUpload,
  rows = 18,
  placeholder,
}: {
  value: string;
  onChange: (next: string) => void;
  /** Stores a pasted or dropped file and says where it now lives. Without
   * it, the file buttons are hidden rather than offering a broken action. */
  onUpload?: (file: File) => Promise<Upload>;
  rows?: number;
  placeholder?: string;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const [mode, setMode] = useState<Mode>("split");
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  // A Markdown or text file, held until the writer says whether they want
  // its text in the body or the file attached.
  const [textFile, setTextFile] = useState<File | null>(null);

  const replaceSelection = (build: (selected: string) => { text: string; cursor?: number }) => {
    const el = area.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = value.slice(start, end);
    const { text, cursor } = build(selected);
    const next = value.slice(0, start) + text + value.slice(end);
    onChange(next);
    // Put the caret where the writer would expect to keep typing.
    requestAnimationFrame(() => {
      el.focus();
      const at = start + (cursor ?? text.length);
      el.setSelectionRange(at, at);
    });
  };

  const apply = (action: Action) => {
    if (action.block) {
      replaceSelection(() => ({ text: action.block! }));
      return;
    }
    if (action.linePrefix) {
      replaceSelection((selected) => {
        const lines = (selected || "").split("\n");
        return {
          text: lines.map((line) => `${action.linePrefix}${line}`).join("\n"),
        };
      });
      return;
    }
    const [before, after] = action.wrap!;
    replaceSelection((selected) => {
      const body = selected || action.placeholder || "";
      return {
        text: `${before}${body}${after}`,
        cursor: selected ? undefined : before.length + body.length,
      };
    });
  };

  /** A file arriving by Attach, drop or paste. */
  const receive = (file: File) => {
    if (isTextDocument(file)) {
      setFailure(null);
      setTextFile(file);
      return;
    }
    insertUpload(file);
  };

  const insertText = async (file: File) => {
    setTextFile(null);
    const text = (await file.text()).replace(/\r\n/g, "\n").trim();
    if (!value.trim()) {
      onChange(`${text}\n`);
      return;
    }
    if (!area.current) {
      // Preview only: no caret to insert at, so it goes at the end.
      onChange(`${value.trimEnd()}\n\n${text}\n`);
      return;
    }
    replaceSelection(() => ({ text: `\n${text}\n` }));
  };

  const insertUpload = async (file: File) => {
    if (!onUpload) return;
    setTextFile(null);
    setFailure(null);
    setBusy(file.name);
    try {
      const { url, filename, isImage } = await onUpload(file);
      const snippet = isImage ? `\n![${filename}](${url})\n` : `\n[${filename}](${url})\n`;
      replaceSelection(() => ({ text: snippet }));
    } catch (e) {
      // The server's own words, not a shrug. "That revision is closed —
      // start a new revision to add files" tells someone what to do;
      // "could not attach" sends them looking for a fault that isn't there.
      const detail = e instanceof ApiError ? e.detail : null;
      setFailure(detail ?? (e instanceof Error ? e.message : `Could not attach ${file.name}.`));
    } finally {
      setBusy(null);
    }
  };

  const showWrite = mode !== "preview";
  const showPreview = mode !== "write";

  return (
    <div className="rounded border border-slate-300 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-2 py-1.5">
        {ACTIONS.map((group, i) => (
          <div key={i} className="flex items-center gap-0.5 border-r border-slate-200 pr-2 last:border-0">
            {group.map((action) => (
              <button
                key={action.title}
                type="button"
                title={action.title}
                onClick={() => apply(action)}
                className={`h-7 min-w-7 rounded px-1.5 text-xs text-slate-600 hover:bg-slate-100 ${
                  action.mono ? "font-mono" : ""
                } ${action.label === "B" ? "font-bold" : ""} ${
                  action.label === "I" ? "italic" : ""
                }`}
              >
                {action.label}
              </button>
            ))}
          </div>
        ))}

        {onUpload && (
          <label className="cursor-pointer rounded px-1.5 py-1 text-xs text-slate-600 hover:bg-slate-100">
            {busy ? `Attaching ${busy}…` : "📎 Attach"}
            <input
              type="file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) receive(file);
              }}
            />
          </label>
        )}

        <div className="ml-auto flex gap-1 rounded bg-slate-100 p-0.5">
          {(["write", "split", "preview"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-2 py-0.5 text-xs capitalize ${
                mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div className={showWrite && showPreview ? "grid grid-cols-2 divide-x divide-slate-200" : ""}>
        {showWrite && (
          <textarea
            ref={area}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            rows={rows}
            placeholder={placeholder}
            onDragOver={(e) => {
              if (!onUpload) return;
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              if (!onUpload) return;
              e.preventDefault();
              setDragOver(false);
              const file = e.dataTransfer.files?.[0];
              if (file) receive(file);
            }}
            onPaste={(e) => {
              // A screenshot in the clipboard is the fastest way anyone
              // documents what they just saw on a control screen.
              if (!onUpload) return;
              const file = Array.from(e.clipboardData.files)[0];
              if (file) {
                e.preventDefault();
                receive(file);
              }
            }}
            className={`w-full resize-y px-3 py-2 font-mono text-sm outline-none ${
              dragOver ? "bg-indigo-50" : ""
            }`}
          />
        )}
        {showPreview && (
          <div className="max-h-[40rem] overflow-y-auto px-3 py-2">
            <MarkdownView markdown={value} />
          </div>
        )}
      </div>

      {textFile && (
        <div className="flex flex-wrap items-center gap-2 border-t border-indigo-100 bg-indigo-50 px-3 py-2 text-xs text-indigo-900">
          <span>
            <b>{textFile.name}</b> is a text document.
          </span>
          <button
            type="button"
            onClick={() => insertText(textFile)}
            className="rounded bg-slate-900 px-2 py-1 font-medium text-white hover:bg-slate-800"
          >
            {value.trim() ? "Insert its text here" : "Use its text as the body"}
          </button>
          <button
            type="button"
            onClick={() => insertUpload(textFile)}
            className="rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50"
          >
            Attach it as a file
          </button>
          <button type="button" onClick={() => setTextFile(null)} className="text-slate-500 hover:underline">
            Cancel
          </button>
        </div>
      )}

      {failure && (
        <p className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
          {failure}
        </p>
      )}

      {onUpload && !failure && (
        <p className="border-t border-slate-100 px-3 py-1 text-[11px] text-slate-400">
          Drop a file here, or paste a screenshot, to attach it.
        </p>
      )}
    </div>
  );
}
