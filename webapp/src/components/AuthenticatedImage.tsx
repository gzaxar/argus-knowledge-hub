import { useEffect, useState } from "react";
import { attachmentsApi } from "../api/client";

export function AuthenticatedImage({
  uid,
  alt,
  className,
  style,
  fetchBlobUrl = attachmentsApi.fetchBlobUrl,
}: {
  uid: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
  /** Defaults to fetching from /v1/attachments/{uid}; pass a different
   * fetcher (e.g. iconsApi.fetchBlobUrl) to render from another endpoint. */
  fetchBlobUrl?: (uid: string) => Promise<string>;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchBlobUrl(uid)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setSrc(url);
      })
      .catch(() => {
        setSrc(null);
        setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [uid]);

  if (!src) {
    return (
      <div
        className={`flex items-center justify-center bg-slate-100 text-slate-400 ${className ?? ""}`}
        style={style}
        // The print view waits for these before opening the print dialog.
        data-loading={failed ? undefined : ""}
      >
        …
      </div>
    );
  }
  return <img src={src} alt={alt} className={className} style={style} />;
}
