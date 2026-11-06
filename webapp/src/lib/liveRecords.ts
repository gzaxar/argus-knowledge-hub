import type { Asset } from "../api/types";

/** Still in use: not deleted, retired or merged. Those keep their history and open by their link, but what
 *  looks for records does not offer them. */
export const isLive = (a: Pick<Asset, "deleted_at" | "record_status">) =>
  !a.deleted_at && a.record_status !== "Retired" && a.record_status !== "Merged";
