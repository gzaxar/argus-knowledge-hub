import { ApiError } from "../api/client";

/** Whether a failed request is a refusal to tell the person about. A query that asks "may I?" on purpose
 *  (`meta.expect403`, such as a page finding out whether it is in the catalogue workspace) reads the refusal as an
 *  answer: telling "You don't have permission" for it alarms an administrator who did nothing wrong. */
export function refusalToTell(error: unknown, meta?: Record<string, unknown>): boolean {
  return error instanceof ApiError && error.status === 403 && !meta?.expect403;
}
