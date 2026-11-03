import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { useEffect, useState, type ReactNode } from "react";
// Use the existing API helper so attachment requests include authentication
// and resolve against the configured API address.
import { attachmentsApi } from "../api/client";
import { AuthenticatedImage } from "./AuthenticatedImage";
import { ImageLightbox } from "./ImageLightbox";

/** An attachment URL written by the importer or the editor. The file is
 * behind the API's Bearer auth, so a plain <img src> can't fetch it. */
const ATTACHMENT_URL = /^\/v1\/attachments\/([A-Za-z0-9-]+)$/;

// Imported content (a Jira custom field, a Confluence macro that slipped through) is sometimes raw HTML
// rather than Markdown, e.g. `<div class="created-with-ak-editor">…</div>`. rehype-raw parses that HTML
// into the tree alongside the Markdown; rehype-sanitize then strips anything unsafe to render (scripts,
// inline event handlers, iframes), on top of what Markdown itself produces.
const sanitizeSchema = {
  ...defaultSchema,
  attributes: { ...defaultSchema.attributes, "*": [...(defaultSchema.attributes?.["*"] ?? []), "className"] },
};

/** A document body, rendered.
 *
 * Imported pages are Markdown — tables of vacuum parameters, numbered
 * procedure steps, code blocks of commands, warnings that must stand out.
 * Showing that as raw text is showing the reader the syntax instead of the
 * document.
 */
export function MarkdownView({
  markdown,
  className = "",
  codeLink,
}: {
  markdown: string;
  className?: string;
  /** Where an inline code span links to, when it names a record (`SPARC:ELM:SBNQUA01`). */
  codeLink?: (text: string) => string | undefined;
}) {
  if (!markdown?.trim()) {
    return <p className={`text-sm text-slate-400 ${className}`}>—</p>;
  }

  return (
    <div className={`markdown-body text-sm leading-relaxed text-slate-700 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-5 border-b border-slate-200 pb-1 text-xl font-semibold text-slate-900 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-5 text-lg font-semibold text-slate-900 first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-4 text-base font-semibold text-slate-800 first:mt-0">
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4 className="mb-1 mt-3 text-sm font-semibold text-slate-800">{children}</h4>
          ),
          p: ({ children }) => <p className="my-2">{children}</p>,
          a: ({ href, children }) => {
            // Attachment links require Bearer authentication, just like images.
            // Opening their relative URL directly can reach the frontend instead
            // of the API. Prepare an authenticated Blob URL before navigation.
            const attachment = href?.match(ATTACHMENT_URL);

            if (attachment) {
              return (
                <AttachmentLink key={attachment[1]} uid={attachment[1]}>
                  {children}
                </AttachmentLink>
              );
            }

            // A page of ARGUS itself (a record an answer cites) opens here, like any other link in the app.
            if (href && /^\/(assets|tickets|documents)\//.test(href)) {
              return (
                <Link
                  to={href}
                  className="text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-600"
                >
                  {children}
                </Link>
              );
            }
            // Other links retain their normal browser behavior.
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-600"
              >
                {children}
              </a>
            );
          },
          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-6">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-6">{children}</ol>,
          li: ({ children }) => <li className="pl-0.5">{children}</li>,
          blockquote: ({ children }) => (
            // Confluence panels land here — a safety warning has to read as
            // one, not as another paragraph.
            <blockquote className="my-3 border-l-4 border-amber-300 bg-amber-50 py-1 pl-3 pr-2 text-slate-700">
              {children}
            </blockquote>
          ),
          code: ({ className: lang, children, ...props }) => {
            const inline = !String(lang ?? "").startsWith("language-");
            if (inline) {
              const target = codeLink?.(String(children ?? "").trim());
              if (target) {
                return (
                  <Link to={target} className="rounded bg-indigo-50 px-1 py-0.5 font-mono text-[0.85em] text-indigo-700 hover:underline">
                    {children}
                  </Link>
                );
              }
              return (
                <code
                  className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] text-slate-800"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className="font-mono text-xs text-slate-100" {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="my-3 overflow-x-auto rounded bg-slate-900 p-3 text-slate-100">
              {children}
            </pre>
          ),
          // Wide tables scroll inside their own box rather than pushing the
          // page sideways — a parameter table is usually the widest thing
          // on the page.
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded border border-slate-200">
              <table className="w-full border-collapse text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b border-slate-200 px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-slate-100 px-3 py-1.5 align-top">{children}</td>
          ),
          hr: () => <hr className="my-4 border-slate-200" />,
          img: ({ src, alt }) => {
            const match = typeof src === "string" ? src.match(ATTACHMENT_URL) : null;
            if (match) {
              return <InlineImage uid={match[1]} alt={alt ?? ""} />;
            }
            return (
              <img
                src={src}
                alt={alt ?? ""}
                className="my-3 max-w-full rounded border border-slate-200"
              />
            );
          },
          input: ({ checked, type }) =>
            type === "checkbox" ? (
              <input type="checkbox" checked={!!checked} readOnly className="mr-1 align-middle" />
            ) : null,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

/**
 * A protected attachment linked from the document body.
 *
 * Fetch through the existing authenticated API helper and render a normal
 * link to the resulting Blob URL. Fetching when this component mounts
 * allows the eventual click to open a new tab synchronously, avoiding
 * popup blocking caused by opening a window after an asynchronous request.
 *
 * This preloads each linked attachment when the document is rendered.
 */
function AttachmentLink({
  uid,
  children,
}: {
  uid: string;
  children: ReactNode;
}) {
  // Associate the result with its attachment so a previous URL is never
  // displayed if this component receives a different uid.
  const [result, setResult] = useState<{
    uid: string;
    url: string | null;
    failed: boolean;
  } | null>(null);

  // Incrementing this value retries a failed request.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    attachmentsApi.fetchBlobUrl(uid)
      .then((url) => {
        // A request may finish after unmounting or after uid changes.
        // Release that unused URL instead of updating stale state.
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }

        objectUrl = url;
        setResult({ uid, url, failed: false });
      })
      .catch(() => {
        if (!cancelled) {
          setResult({ uid, url: null, failed: true });
        }
      });

    // Release the Blob URL when this effect is replaced or unmounted,
    // following the existing AuthenticatedImage cleanup pattern.
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [uid, attempt]);

  const current = result?.uid === uid ? result : null;
  const linkClass =
    "text-indigo-600 underline decoration-indigo-300 " +
    "underline-offset-2 hover:decoration-indigo-600";

  // Keep failures visible and let the reader retry without reloading
  // the whole document.
  if (current?.failed) {
    return (
      <span>
        <button
          type="button"
          className={linkClass}
          title="Retry loading attachment"
          onClick={() => {
            setResult(null);
            setAttempt((value) => value + 1);
          }}
        >
          {children}
        </button>
        <span role="status" className="ml-1 text-xs text-red-600">
          Unable to load attachment. Click to retry or use FILES → Download.
        </span>
      </span>
    );
  }

  // Do not expose the original unauthenticated URL while loading.
  if (!current?.url) {
    return (
      <span aria-busy="true" className="text-slate-500">
        {children}
        <span role="status" className="ml-1 text-xs">
          (Loading…)
        </span>
      </span>
    );
  }

  // The browser opens the fetched file. PDF display depends on the
  // MIME type preserved by fetchBlobUrl and the browser's settings.
  return (
    <a
      href={current.url}
      target="_blank"
      rel="noopener noreferrer"
      className={linkClass}
    >
      {children}
    </a>
  );
}
/** An image in the text, at most as wide as the text; a click shows it full size. */
function InlineImage({ uid, alt }: { uid: string; alt: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title="Show full size" className="my-3 block cursor-zoom-in">
        <AuthenticatedImage uid={uid} alt={alt} className="max-h-[32rem] max-w-full rounded border border-slate-200" />
      </button>
      {open && <ImageLightbox uid={uid} alt={alt} onClose={() => setOpen(false)} />}
    </>
  );
}
