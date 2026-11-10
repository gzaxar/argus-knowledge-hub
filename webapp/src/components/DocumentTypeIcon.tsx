import { iconsApi } from "../api/client";
import { AuthenticatedImage } from "./AuthenticatedImage";

/** Use the type's configured icon, just as the existing TypeExplorer does. */
export function DocumentTypeIcon({ iconUid }: { iconUid?: string | null }) {
  if (iconUid) return <AuthenticatedImage uid={iconUid} alt="" fetchBlobUrl={iconsApi.fetchBlobUrl}
                                        className="h-3.5 w-3.5 shrink-0 object-contain" />;
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5 shrink-0">
    <path d="M6 3h9l4 4v14H6zM15 3v5h4" /><path d="M9 12h7M9 16h7" />
  </svg>;
}
