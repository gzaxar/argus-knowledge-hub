import { useQuery } from "@tanstack/react-query";
import { workspacesApi } from "../api/client";
import type { MyWorkspace } from "../api/types";
import { getActiveProfile } from "../api/session";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";

export type Rights = Pick<MyWorkspace, "can_create" | "can_modify" | "can_delete" | "can_create_tickets" |
  "can_modify_tickets" | "can_delete_tickets" | "can_create_documents" | "can_modify_documents" | "can_delete_documents">;

const ALL: Rights = {
  can_create: true, can_modify: true, can_delete: true, can_create_tickets: true, can_modify_tickets: true,
  can_delete_tickets: true, can_create_documents: true, can_modify_documents: true, can_delete_documents: true,
};

/** What the signed-in person may do in the current workspace, to show only the actions they can take. A token
 * acts for its workspace, and the server checks every action anyway: unknown rights show the action. */
export function useRights(): Rights {
  const ws = useCurrentWorkspaceId();
  const oidc = getActiveProfile()?.authType === "oidc";
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine, enabled: oidc, staleTime: 60_000 });
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me, staleTime: 60_000 });
  if (!oidc || me.data?.is_admin) return ALL;
  const row = mine.data?.find((w) => w.id === ws);
  return row ?? ALL;
}
