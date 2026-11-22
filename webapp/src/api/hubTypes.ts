/** Types of the unified knowledge layer (`/v1/hub`, backend/app/routers/hub.py). */

export interface HubAsset {
  uid: string;
  key: string;
  name: string;
  type: string;
  schema_uid: string;
  workspace_id: string;
  lifecycle?: string | null;
  system?: string | null;
  updated_at?: string | null;
}

export interface HubTicket {
  uid: string;
  title: string;
  state: string;
  priority?: string | null;
  assignee?: string | null;
  asset_uid?: string | null;
  open: boolean;
  source_key?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  due_date?: string | null;
}

/** Why a document applies to an asset. */
export type KnowledgeVia = "asset" | "product" | "type" | "service";

export interface HubDocument {
  uid: string;
  code: string;
  title: string;
  authority_level: string;
  workspace_id: string;
  is_global: boolean;
  state?: string | null;
  next_review_due?: string | null;
  review_overdue: boolean;
  updated_at?: string | null;
  via?: KnowledgeVia | null;
  via_label?: string | null;
  for_assets?: { uid: string; name: string }[];
}

export interface HubNeighbour extends HubAsset {
  relation: string;
  direction: "in" | "out";
}

export interface ExternalTicket {
  key: string;
  summary: string;
  status: string;
  type: string;
  url?: string | null;
  updated?: string | null;
}

export interface AssetContext {
  asset: HubAsset;
  /** Set while the derive stage is catching up with an edit (I-UX-1). */
  processing: { state: "deriving"; since: string; request: number } | null;
  /** The restricted class of this record, when it has one. */
  restricted: string | null;
  /** For a merge tombstone: where it went, and the merge to undo. */
  merged: { into: HubAsset | null; decision_id: string | null } | null;
  type_path: string[];
  access: { tickets: boolean; documents: boolean };
  stats: {
    open_tickets: number;
    tickets: number;
    external_tickets: number;
    documents: number;
    documents_overdue: number;
    relations: number;
  };
  tickets: HubTicket[];
  external_tickets: ExternalTicket[];
  documents: HubDocument[];
  relations: { total: number; by_relation: Record<string, number>; items: HubNeighbour[] };
}

export interface TicketContext {
  ticket: HubTicket;
  access: { assets: boolean; documents: boolean };
  assets: HubAsset[];
  suggested_documents: HubDocument[];
  concurrent_tickets: HubTicket[];
}

export interface DocumentContext {
  document: HubDocument;
  access: { assets: boolean; tickets: boolean };
  assets: HubAsset[];
  instances: HubAsset[];
  types: { uid: string; name: string; assets: number }[];
  open_tickets: HubTicket[];
}

export interface HubSearchResult {
  query: string;
  assets: HubAsset[];
  tickets: HubTicket[];
  documents: HubDocument[];
}

/** One step of the cockpit's *Start here*: done once the workspace has one. */
export interface HubStartStep {
  key: "places" | "equipment" | "records" | "people" | "document" | "ticket";
  count: number;
  done: boolean;
  /** places: the Building type, to open the form on it */
  type_uid?: string | null;
}

export interface HubOverview {
  access: { assets: boolean; tickets: boolean; documents: boolean };
  /** How far the workspace is in being set up (absent from an older server). */
  start?: { steps: HubStartStep[]; done: boolean };
  assets?: { own: number; recent: HubAsset[] };
  tickets?: {
    open: number;
    total: number;
    by_state: Record<string, number>;
    by_priority: Record<string, number>;
    mine: HubTicket[];
    unassigned: number;
    without_asset: number;
    hotspots: (HubAsset & { open_tickets: number })[];
    recent: HubTicket[];
  };
  documents?: {
    total: number;
    in_review: number;
    awaiting_review: HubDocument[];
    review_overdue: HubDocument[];
    not_linked_to_assets: number;
    recent: HubDocument[];
  };
}
