import { MenuButton, ViewSwitch } from "./browse/Browse";
import type { Rights } from "../lib/permissions";

export type DocumentView = "list" | "tree" | "board";

/** List | Tree | Board, as Tickets have List | Board and Assets List | Map: the filters in the address follow. */
export function DocumentViewSwitch({ current }: { current: DocumentView }) {
  return <ViewSwitch views={[
    { label: "List", to: "/documents", current: current === "list" },
    { label: "Tree", to: "/documents/tree", current: current === "tree" },
    { label: "Board", to: "/documents/board", current: current === "board" },
  ]} />;
}

/** The documents' Tools menu, the same in every view. */
export function DocumentTools({ rights }: { rights: Rights }) {
  return <MenuButton label="Tools" items={[
    { to: "/documents/templates", label: "Templates", hint: "The skeleton each document type starts from" },
    ...(rights.can_create_documents
      ? [{ to: "/documents/reshape", label: "Rework from raw text", hint: "Notes, an e-mail or a transcript, rewritten as a draft" }]
      : []),
    { to: "/search/advanced?entity=documents", label: "Advanced query", hint: "Combine conditions on any field" },
    { to: "/documents/suggestions", label: "Type suggestions", hint: "Documents whose type looks wrong" },
  ]} />;
}
