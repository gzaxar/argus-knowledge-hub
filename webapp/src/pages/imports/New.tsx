
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { importPaths } from "./paths";
import { ApiError, importConfigsApi, workspacesApi } from "../../api/client";
import { ImportSchedule, ImportSource, MergeStrategy, MERGE_STRATEGIES } from "../../api/types";
import { WorkspaceScopeBanner } from "../../components/WorkspaceScopeBanner";

export function ImportConfigForm() {
  const { uid, workspaceId } = useParams<{ uid: string; workspaceId: string }>();
  const [searchParams] = useSearchParams();
  const isEdit = !!uid;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const existing = useQuery({
    queryKey: ["import-configs", uid],
    queryFn: () => importConfigsApi.get(uid!),
    enabled: isEdit,
  });

  const [name, setName] = useState("");
  // Opened from a section's Import link, the form starts on that section's
  // source rather than making you pick it again.
  const requestedSource = searchParams.get("source");
  const [source, setSource] = useState<ImportSource>(
    requestedSource === "jira-issues" ||
    requestedSource === "confluence" ||
    requestedSource === "dokuwiki" ||
    requestedSource === "git" ||
    requestedSource === "epik8s"
      ? requestedSource
      : "jira",
  );
  // When it runs again by itself: off, every few hours, daily or weekly at a local time.
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [schedule, setSchedule] = useState<ImportSchedule>({ kind: "off", every_hours: 24, time: "02:00", weekday: 0,
                                                               timezone: browserZone });
  const [mergeStrategy, setMergeStrategy] = useState<MergeStrategy>("override");

  const [baseUrl, setBaseUrl] = useState("");
  const [jiraPat, setJiraPat] = useState("");
  const [jiraSchemaId, setJiraSchemaId] = useState("");

  const [jql, setJql] = useState("");
  const [spaceKey, setSpaceKey] = useState("");
  const [cql, setCql] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [linkAssets, setLinkAssets] = useState(true);

  const [provider, setProvider] = useState<"github" | "gitlab">("github");
  const [repoUrl, setRepoUrl] = useState("");
  const [gitPat, setGitPat] = useState("");
  const [branch, setBranch] = useState("main");
  const [valuesPath, setValuesPath] = useState("deploy/values.yaml");
  const [createMissingNodes, setCreateMissingNodes] = useState(true);
  // The chain the configuration implies, each one optional.
  const [inferElements, setInferElements] = useState(false);
  const [inferControllers, setInferControllers] = useState(false);
  const [itWorkspace, setItWorkspace] = useState("");
  const [linkInventory, setLinkInventory] = useState(true);
  const [aiUnrecognised, setAiUnrecognised] = useState(false);
  const myWorkspaces = useQuery({
    queryKey: ["my-workspaces"],
    queryFn: workspacesApi.listMine,
    staleTime: 60_000,
    enabled: source === "epik8s",
  });

  // params holds whatever the source needs, so values arrive loosely typed.
  const param = (key: string) => {
    const value = existing.data?.params[key];
    return typeof value === "string" ? value : "";
  };

  useEffect(() => {
    if (!existing.data) return;
    setName(existing.data.name);
    setSource(existing.data.source);
    // A configuration saved with the retired "remove all before" runs as
    // override on the server; saving it again records that.
    const stored = existing.data.merge_strategy as string;
    setMergeStrategy(stored === "remove_all_before" ? "override" : (stored as MergeStrategy));
    if (existing.data.source === "jira") {
      setBaseUrl(param("base_url"));
      setJiraSchemaId(param("jira_schema_id"));
    } else if (existing.data.source === "confluence") {
      setBaseUrl(param("base_url"));
      setSpaceKey(param("space_key"));
      setCql(param("cql"));
      setPageUrl(param("page_url"));
      setIncludeChildren(existing.data.params.include_children !== false);
      setLinkAssets(existing.data.params.link_assets !== false);
    } else if (existing.data.source === "dokuwiki") {
      setPageUrl(param("page_url"));
      setIncludeChildren(existing.data.params.include_children !== false);
      setLinkAssets(existing.data.params.link_assets !== false);
    } else if (existing.data.source === "jira-issues") {
      setBaseUrl(param("base_url"));
      setJql(param("jql"));
      setLinkAssets(existing.data.params.link_assets !== false);
    } else {
      setProvider((param("provider") as "github" | "gitlab") || "github");
      setRepoUrl(param("repo_url"));
      setBranch(param("branch") || "main");
      setValuesPath(param("path") || "deploy/values.yaml");
      setCreateMissingNodes(existing.data.params.create_missing_nodes !== false);
      setInferElements(existing.data.params.infer_elements === true);
      setInferControllers(existing.data.params.infer_controllers === true);
      setItWorkspace(param("it_workspace"));
      setLinkInventory(existing.data.params.link_inventory !== false);
      setAiUnrecognised(existing.data.params.ai_unrecognised === true);
    }
    const d = existing.data;
    setSchedule({ kind: d.schedule_kind ?? "off", every_hours: d.schedule_every_hours ?? 24, time: d.schedule_time ?? "02:00",
                  weekday: d.schedule_weekday ?? 0, timezone: d.schedule_timezone ?? browserZone });
  }, [existing.data]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const config =
        source === "jira"
          ? {
              source: "jira" as const,
              base_url: baseUrl.replace(/\/+$/, ""),
              jira_schema_id: jiraSchemaId,
              ...(jiraPat ? { pat: jiraPat } : {}),
            }
          : source === "confluence"
          ? {
              source: "confluence" as const,
              base_url: baseUrl.replace(/\/+$/, "") || undefined,
              ...(pageUrl.trim()
                ? { page_url: pageUrl.trim(), include_children: includeChildren }
                : { space_key: spaceKey || undefined, cql: cql || undefined }),
              link_assets: linkAssets,
              ...(jiraPat ? { pat: jiraPat } : {}),
            }
          : source === "dokuwiki"
          ? {
              source: "dokuwiki" as const,
              page_url: pageUrl.trim(),
              include_children: includeChildren,
              link_assets: linkAssets,
            }
          : source === "jira-issues"
          ? {
              source: "jira-issues" as const,
              base_url: baseUrl.replace(/\/+$/, ""),
              jql,
              link_assets: linkAssets,
              ...(jiraPat ? { pat: jiraPat } : {}),
            }
          : source === "epik8s"
          ? {
              source: "epik8s" as const,
              provider,
              repo_url: repoUrl,
              branch,
              path: valuesPath,
              create_missing_nodes: createMissingNodes,
              infer_elements: inferElements,
              infer_controllers: inferElements && inferControllers,
              it_workspace: itWorkspace || null,
              link_inventory: inferElements && linkInventory,
              ai_unrecognised: inferElements && aiUnrecognised,
              ...(gitPat ? { pat: gitPat } : {}),
            }
          : {
              source: "git" as const,
              provider,
              repo_url: repoUrl,
              branch,
              ...(gitPat ? { pat: gitPat } : {}),
            };
      const when: ImportSchedule = schedule.kind === "off" ? { kind: "off" }
        : schedule.kind === "hours" ? { kind: "hours", every_hours: schedule.every_hours }
        : schedule.kind === "daily" ? { kind: "daily", time: schedule.time, timezone: schedule.timezone }
        : { kind: "weekly", weekday: schedule.weekday, time: schedule.time, timezone: schedule.timezone };
      if (isEdit) {
        return importConfigsApi.update(uid!, { name, merge_strategy: mergeStrategy, config, schedule: when });
      }
      return importConfigsApi.create({ name, merge_strategy: mergeStrategy, config, schedule: when });
    },
    onSuccess: async (saved) => {
      queryClient.invalidateQueries({ queryKey: ["import-configs"] });
      if (!isEdit) {
        // First save also runs it immediately — reuse it later via "Run" on the list.
        const running = await importConfigsApi.run(saved.uid);
        navigate(
          running.last_import_job_uid
            ? importPaths.job(workspaceId!, running.last_import_job_uid)
            : importPaths.list(workspaceId!),
        );
      } else {
        navigate(importPaths.list(workspaceId!));
      }
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    saveMutation.mutate();
  };

  if (isEdit && existing.isLoading) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  return (
    <div className="max-w-lg">
      <h1 className="text-2xl font-semibold text-slate-900">
        {isEdit ? "Edit import configuration" : "New import configuration"}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Saved once, then re-run any time with one click from the Imports list. Existing
        schemas/assets are matched by key — the merge strategy below controls what happens
        when a match is found.
      </p>

      <WorkspaceScopeBanner action="This import writes into" />

      <div className="mt-6 flex gap-2">
        {(["jira", "jira-issues", "confluence", "dokuwiki", "git", "epik8s"] as const).map((s) => (
          <button
            key={s}
            type="button"
            disabled={isEdit}
            onClick={() => setSource(s)}
            className={`rounded px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
              source === s ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {s === "jira"
              ? "Jira objects"
              : s === "jira-issues"
                ? "Jira tickets"
                : s === "confluence"
                  ? "Confluence"
                  : s === "dokuwiki"
                  ? "DokuWiki"
                  : s === "git"
                    ? "Git"
                    : "EPIK8s control"}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="mt-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-slate-700">Configuration name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Nightly Jira sync"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        {source === "dokuwiki" ? (
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-slate-700">A wiki page&apos;s link</label>
              <input
                value={pageUrl}
                onChange={(e) => setPageUrl(e.target.value)}
                placeholder="https://wiki.infn.it/strutture/lnf/da/btf/dispositivi/stages"
                required
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
              />
              <p className="mt-1 text-xs text-slate-500">
                A DokuWiki page (such as wiki.infn.it). Read as anyone allowed to read the wiki reads it: no token. Only
                the wikis this installation allows can be imported.
              </p>
            </div>
            <Check checked={includeChildren} onChange={setIncludeChildren} label="And every page under it"
                   hint="Its folder (namespace) and the folders below; a page under another becomes that document's child." />
            <Check checked={linkAssets} onChange={setLinkAssets} label="Link the equipment a page names"
                   hint="An asset key found in a page links the document to that asset." />
            <p className="text-xs text-slate-500">
              Each wiki page is one document, found again on the next run: unchanged pages are skipped, a changed one
              gets a new revision. Pictures are attached and shown in place; links between imported pages lead to their
              documents.
            </p>
          </div>
        ) : source === "jira" || source === "jira-issues" || source === "confluence" ? (
          <>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                {source === "confluence" ? "Confluence server URL" : "Jira server URL"}
              </label>
              <input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={
                  source === "confluence"
                    ? "https://wiki.example.org/confluence"
                    : source === "jira-issues"
                      ? "https://issues.example.org/jira"
                      : "https://servicedesk.example.org"
                }
                required={!(source === "confluence" && pageUrl.trim())}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-slate-500">
                {source === "confluence"
                  ? "Include the context path if the server has one — Confluence is often published under /confluence or /wiki rather than at the site root. The import checks both. Leave it empty when you give a page link below."
                  : "Include the context path if the server has one — many Jira installations live under /jira rather than at the site root. The import checks both."}
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Personal access token{isEdit && " (leave blank to keep the saved one)"}
              </label>
              <input
                type="password"
                value={jiraPat}
                onChange={(e) => setJiraPat(e.target.value)}
                required={!isEdit}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            {source === "confluence" ? (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700">A page link</label>
                  <input
                    value={pageUrl}
                    onChange={(e) => setPageUrl(e.target.value)}
                    placeholder="https://wiki.example.org/x/YwX6AQ"
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    The short link from the page's Share button, or the page's address. The token's
                    account must be able to open the page.
                  </p>
                  {pageUrl.trim() && (
                    <label className="mt-2 flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={includeChildren}
                        onChange={(e) => setIncludeChildren(e.target.checked)}
                      />
                      And every page under it
                    </label>
                  )}
                </div>
                {!pageUrl.trim() && (
                <>
                <div>
                  <label className="block text-sm font-medium text-slate-700">Or a space key</label>
                  <input
                    value={spaceKey}
                    onChange={(e) => setSpaceKey(e.target.value)}
                    placeholder="LNF"
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Or a CQL query
                  </label>
                  <input
                    value={cql}
                    onChange={(e) => setCql(e.target.value)}
                    placeholder='space = LNF AND label = "procedure"'
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    Pages become documents, typed from their labels. Bodies are converted to
                    Markdown; re-importing a page whose version hasn't changed adds no revision.
                  </p>
                </div>
                </>
                )}
                <label className="flex items-start gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={linkAssets}
                    onChange={(e) => setLinkAssets(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Link documents to objects they mention
                    <span className="block text-xs text-slate-500">
                      A page whose text contains an object key (LNFT2-145356) is attached to it.
                    </span>
                  </span>
                </label>
              </>
            ) : source === "jira" ? (
              <div>
                <label className="block text-sm font-medium text-slate-700">Object schema ID</label>
                <input
                  value={jiraSchemaId}
                  onChange={(e) => setJiraSchemaId(e.target.value)}
                  placeholder="32"
                  required
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Which issues (a Jira search query)
                  </label>
                  <input
                    value={jql}
                    onChange={(e) => setJql(e.target.value)}
                    placeholder='project = LNF AND updated >= -90d'
                    required
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    Any query the token's account can run in Jira. Start narrow — one project,
                    recent issues — and widen once the result looks right.
                  </p>
                </div>
                <label className="flex items-start gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={linkAssets}
                    onChange={(e) => setLinkAssets(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Link tickets to objects they mention
                    <span className="block text-xs text-slate-500">
                      A ticket whose text contains an object key (LNFT2-145356) is attached to
                      that object.
                    </span>
                  </span>
                </label>
              </>
            )}
          </>
        ) : (
          <>
            <div>
              <label className="block text-sm font-medium text-slate-700">Provider</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value as "github" | "gitlab")}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="github">GitHub</option>
                <option value="gitlab">GitLab</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Repository URL</label>
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
                required
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Personal access token{isEdit && " (leave blank to keep the saved one)"}
              </label>
              <input
                type="password"
                value={gitPat}
                onChange={(e) => setGitPat(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-slate-500">
                {isEdit
                  ? "Leave blank to keep whatever is saved."
                  : "Leave blank for a public repository — no token is sent at all, rather than an empty one."}
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Branch</label>
              <input
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>

            {source === "epik8s" && (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Path to the beamline configuration
                  </label>
                  <input
                    value={valuesPath}
                    onChange={(e) => setValuesPath(e.target.value)}
                    placeholder="deploy/values.yaml"
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    One beamline per configuration. Read only — the file in git deploys
                    the accelerator, and each imported object records the revision it
                    came from.
                  </p>
                </div>
                <label className="flex items-start gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={createMissingNodes}
                    onChange={(e) => setCreateMissingNodes(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Create an object for an address nothing in the inventory carries
                    <span className="block text-xs text-slate-500">
                      Addresses are matched to equipment you already hold — a terminal
                      server is linked, not duplicated. The rest become Access Points
                      marked as needing confirmation. Unchecked, they are only listed in
                      the import's warnings.
                    </span>
                  </span>
                </label>

                <fieldset className="rounded border border-slate-200 p-3">
                  <legend className="px-1 text-sm font-medium text-slate-700">
                    Infer the hardware chain
                  </legend>
                  <p className="mb-2 text-xs text-slate-500">
                    The file names channels, not hardware. These options make what the
                    channels imply, marked as inferred and waiting for someone to confirm.
                  </p>
                  <div className="space-y-2">
                    <Check
                      checked={inferElements}
                      onChange={setInferElements}
                      label="Infer equipment and lattice elements (rules)"
                      hint="The pumps, gauges, magnets, supplies, cameras and BPM electronics the channels drive, from the channel metadata and the naming convention. Needs the type catalogue seeded."
                    />
                    <div className={`space-y-2 pl-6 ${inferElements ? "" : "opacity-50"}`}>
                      <Check
                        checked={inferControllers}
                        disabled={!inferElements}
                        onChange={setInferControllers}
                        label="Infer controllers"
                        hint="The box an IOC talks to (an IPCMini, a TPG 366, a Pollux chain), powering what its channels drive and reached through the IOC's address."
                      />
                      <Check
                        checked={linkInventory}
                        disabled={!inferElements}
                        onChange={setLinkInventory}
                        label="Link to units already in the inventory"
                        hint="When the inventory holds the unit (same tag, or the same network address), the channel is proposed as linked to it instead of getting an inferred twin. You confirm links under Assets → Channels ↔ hardware."
                      />
                      <Check
                        checked={aiUnrecognised}
                        disabled={!inferElements}
                        onChange={setAiUnrecognised}
                        label="Ask the AI about channels the rules don't recognise"
                        hint="Uses this workspace's AI endpoint. The AI picks from the catalogue's equipment types only, and its answers are proposals in the review queue, never records."
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-slate-700">
                        IT workspace for converters, servers and their ports
                      </label>
                      <select
                        value={itWorkspace}
                        onChange={(e) => setItWorkspace(e.target.value)}
                        className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      >
                        <option value="">None — don't make IT equipment</option>
                        {(myWorkspaces.data ?? []).map((w) => (
                          <option key={w.id} value={w.id}>
                            {w.name}
                          </option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-slate-500">
                        A serial converter or a server named by a hostname is made once
                        there, shared, with the ports the lines use (TCP 4003 → P3). You
                        need permission to create objects in that workspace.
                      </p>
                    </div>
                  </div>
                </fieldset>
              </>
            )}
          </>
        )}

        <ScheduleFields value={schedule} onChange={setSchedule} />

        <div>
          <label className="block text-sm font-medium text-slate-700">
            When a matching object already exists
          </label>
          <select
            value={mergeStrategy}
            onChange={(e) => setMergeStrategy(e.target.value as MergeStrategy)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            {MERGE_STRATEGIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-400">
            {MERGE_STRATEGIES.find((s) => s.value === mergeStrategy)?.description}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            Imports never delete records: values people edited are kept, and anything the source
            no longer contains is left for review.
          </p>
        </div>

        {saveMutation.isError && (
          <p className="text-sm text-red-600">
            {saveMutation.error instanceof ApiError
              ? JSON.stringify(saveMutation.error.body)
              : "Failed to save configuration"}
          </p>
        )}

        <button
          type="submit"
          disabled={saveMutation.isPending}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {saveMutation.isPending
            ? "Saving…"
            : isEdit
              ? "Save changes"
              : "Save and run now"}
        </button>
      </form>
    </div>
  );
}

function Check({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-start gap-2 text-sm text-slate-700">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5"
      />
      <span>
        {label}
        <span className="block text-xs text-slate-500">{hint}</span>
      </span>
    </label>
  );
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** When the import runs again by itself — the same run as the Run button, as the person who sets it. */
function ScheduleFields({ value, onChange }: { value: ImportSchedule; onChange: (v: ImportSchedule) => void }) {
  const set = (patch: Partial<ImportSchedule>) => onChange({ ...value, ...patch });
  return (
    <fieldset className="rounded border border-slate-200 p-3">
      <legend className="px-1 text-sm font-medium text-slate-700">Run again by itself</legend>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select value={value.kind} onChange={(e) => set({ kind: e.target.value as ImportSchedule["kind"] })}
                className="rounded border border-slate-300 px-2 py-1.5" aria-label="Schedule">
          <option value="off">No — only when I press Run</option>
          <option value="hours">Every few hours</option>
          <option value="daily">Every day</option>
          <option value="weekly">Every week</option>
        </select>
        {value.kind === "hours" && (
          <label className="flex items-center gap-1">every
            <input type="number" min={1} max={168} value={value.every_hours ?? 24}
                   onChange={(e) => set({ every_hours: Number(e.target.value) || 1 })}
                   className="w-20 rounded border border-slate-300 px-2 py-1.5" /> hours</label>
        )}
        {value.kind === "weekly" && (
          <select value={value.weekday ?? 0} onChange={(e) => set({ weekday: Number(e.target.value) })}
                  className="rounded border border-slate-300 px-2 py-1.5" aria-label="Day">
            {WEEKDAYS.map((d, i) => <option key={d} value={i}>on {d}</option>)}
          </select>
        )}
        {(value.kind === "daily" || value.kind === "weekly") && (
          <label className="flex items-center gap-1">at
            <input type="time" value={value.time ?? "02:00"} onChange={(e) => set({ time: e.target.value })}
                   className="rounded border border-slate-300 px-2 py-1.5" />
            <span className="text-xs text-slate-500">({value.timezone})</span></label>
        )}
      </div>
      {value.kind !== "off" && (
        <p className="mt-2 text-xs text-slate-500">
          It runs as you, with your permissions at the time. It does not start while its previous run is still going;
          if it fails you are told, and after 3 failures in a row the schedule switches itself off.
        </p>
      )}
    </fieldset>
  );
}
