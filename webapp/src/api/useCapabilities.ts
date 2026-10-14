import { useQuery } from "@tanstack/react-query";
import { packagesApi, type WorkspaceCapabilities } from "./client";
import { useCurrentWorkspaceId } from "./useCurrentWorkspaceId";

/** What the current workspace's packages let it do (equipment, map, beam model…), so pages it cannot use are
 *  not offered. While unknown (loading, or an older server), everything is shown, as before. */
export function useCapabilities(): WorkspaceCapabilities["features"] | null {
  const ws = useCurrentWorkspaceId();
  const caps = useQuery({
    queryKey: ["capabilities", ws],
    queryFn: () => packagesApi.capabilities(ws!),
    enabled: !!ws,
    staleTime: 5 * 60_000,
    retry: false,
  });
  return caps.data?.features ?? null;
}

/** A feature is shown unless the workspace is known not to have it. */
export function has(features: WorkspaceCapabilities["features"] | null, key: keyof WorkspaceCapabilities["features"]) {
  return features === null || features[key];
}
