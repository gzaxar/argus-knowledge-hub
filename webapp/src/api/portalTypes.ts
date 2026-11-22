/** The service portal of a site (docs/service-portal.md): the requester's side and the site's catalogue. */

export interface PortalSite {
  id: string;
  name: string;
  open: boolean;
  manager: boolean;
  headline: string | null;
  origins: { id: string; name: string }[];
}

export interface PortalRequestTypeCard {
  uid: string;
  slug: string;
  name: string;
  description: string | null;
  allow_attachments: boolean;
}

export interface PortalService {
  uid: string;
  slug: string;
  name: string;
  description: string | null;
  hours: string | null;
  contact: string | null;
  request_types: PortalRequestTypeCard[];
}

export interface PortalCatalogue {
  site: { id: string; name: string };
  open: boolean;
  headline: string;
  welcome: string | null;
  emergency: string | null;
  assistance: boolean;
  helpdesk: PortalRequestTypeCard | null;
  categories: { name: string; services: PortalService[] }[];
  origins: { id: string; name: string }[];
  open_requests: number;
}

export interface PortalField {
  key: string;
  label: string;
  help: string | null;
  required: boolean;
  type: string;
  options: { value: string; label: string }[];
}

export interface PortalForm extends PortalRequestTypeCard {
  guidance: string | null;
  fields: PortalField[];
  service: { uid: string; name: string; description: string | null; hours: string | null; contact: string | null;
    category: string | null };
}

export interface RoutePreview {
  request_type_uid: string;
  request_type_name: string;
  service_name: string;
  team_name: string;
  provider_name: string;
  helpdesk: boolean;
  reason: string;
  version: string;
}

export interface PortalStatus {
  category: "open" | "active" | "waiting" | "done";
  label: string;
}

export interface MyRequestSummary {
  uid: string;
  key: string | null;
  title: string;
  service_name: string;
  request_type_name: string;
  status: PortalStatus;
  created_at: string;
  updated_at: string;
  site_id: string;
  origin_name: string | null;
  unread: boolean;
}

export interface MyRequestDetail extends MyRequestSummary {
  restricted: boolean;
  resolution: string | null;
  resolved_at: string | null;
  can_reply: boolean;
  can_reopen: boolean;
  description: string | null;
  submitted: { key: string; label: string; value: unknown }[];
  conversation: { uid: string; body: string; created_at: string; mine: boolean; author_name: string }[];
  attachments: { uid: string; filename: string; mime_type: string | null; file_size: number | null;
    created_at: string; mine: boolean }[];
  notice?: string;
}

export interface SubmitPayload {
  submission_uid: string;
  request_type_uid: string | null;
  origin_workspace_id: string;
  title: string;
  description: string;
  fields: Record<string, unknown>;
  route_version?: string;
}

export interface SubmitReceipt {
  uid: string;
  key: string | null;
  created: boolean;
  site_id: string;
}

export interface PortalAssistResult {
  articles: { uid: string; code: string; title: string; excerpt: string; workspace_id: string }[];
  ai_available: boolean;
  ai_unavailable_reason: string | null;
  ai: null | {
    error?: string; why?: string; title?: string; summary?: string; request_type_uid?: string | null;
    /** Steps the requester may try first, drawn from `sources` (articles they may read). Empty when none cover it. */
    first_help?: string[];
    sources?: { uid: string; code: string; title: string; workspace_id: string }[];
  };
}

// --------------------------------------------------------------------------- administration

export interface ServiceDeskSettings {
  site_id: string;
  site_name: string;
  enabled: boolean;
  headline: string | null;
  welcome: string | null;
  emergency: string | null;
  helpdesk_request_type_uid: string | null;
  assistance: boolean;
  version: number;
}

export interface AdminRequestType {
  uid: string;
  slug: string;
  name: string;
  description: string | null;
  guidance: string | null;
  schema_uid: string | null;
  fields: { key: string; label?: string | null; help?: string | null; required: boolean }[];
  allow_attachments: boolean;
  active: boolean;
  position: number;
  problems: string[];
}

export interface AdminService {
  uid: string;
  slug: string;
  name: string;
  category: string | null;
  description: string | null;
  hours: string | null;
  contact: string | null;
  provider_workspace_id: string;
  provider_name: string | null;
  team_group_uid: string;
  team_name: string | null;
  active: boolean;
  position: number;
  version: number;
  authorized_by: string | null;
  authorized_at: string | null;
  problems: string[];
  request_types: AdminRequestType[];
  site_id?: string;
  site_name?: string;
}

export interface ServiceDesk {
  settings: ServiceDeskSettings;
  services: AdminService[];
}

export interface ServiceDeskOptions {
  workspaces: { id: string; name: string; may_authorize: boolean;
    ticket_types: { uid: string; name: string; fields: { key: string; label: string; type: string }[] }[] }[];
  groups: { uid: string; name: string }[];
}

export interface ServiceInput {
  name: string;
  slug?: string | null;
  category?: string | null;
  description?: string | null;
  hours?: string | null;
  contact?: string | null;
  provider_workspace_id: string;
  team_group_uid: string;
  position?: number;
}

export interface RequestTypeInput {
  name: string;
  slug?: string | null;
  description?: string | null;
  guidance?: string | null;
  schema_uid?: string | null;
  fields: { key: string; label?: string | null; help?: string | null; required: boolean }[];
  allow_attachments: boolean;
  active: boolean;
  position?: number;
}

export interface TicketServiceRequest {
  service: { uid: string; name: string } | null;
  team: { uid: string; name: string } | null;
  request_type_name: string | null;
  requester: { id: string; name: string | null; email: string | null } | null;
  origin_name: string | null;
  route_reason: string | null;
  submitted: { key: string; label: string; value: unknown }[];
  requester_status: PortalStatus;
  services: { uid: string; name: string; team_group_uid: string }[];
}

export interface WorkspaceQueues {
  services: { uid: string; name: string; team_group_uid: string }[];
  teams: { uid: string; name: string; active: boolean }[];
}
