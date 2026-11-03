import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IntakeProfiles } from "../../components/IntakeProfiles";
import { KnowledgeIndex } from "../../components/KnowledgeIndex";
import { useEffect, useState } from "react";
import { aiApi } from "../../api/client";
import type { ModelSetting } from "../../api/types";
import { ModelSettingsEditor } from "../../components/ModelSettings";

/** Where this workspace's AI features send their requests.
 *
 * Configured here rather than in the deployment because different
 * workspaces are entitled to different gateways — and because a key typed
 * into this form is encrypted at rest without ever travelling through a
 * values file or a chat window to get there.
 */
export function WorkspaceAI() {
  return <AIEndpointSettings scope="workspace" />;
}

/** Administration → AI: the settings every workspace without its own uses. */
export function InstallationAI() {
  return <AIEndpointSettings scope="installation" />;
}

const API = {
  workspace: { key: "ai-config", get: aiApi.getConfig, save: aiApi.saveConfig, check: aiApi.check, remove: aiApi.deleteConfig,
               test: aiApi.testModel },
  installation: { key: "ai-installation-config", get: aiApi.getInstallationConfig, save: aiApi.saveInstallationConfig,
                  check: aiApi.checkInstallationConfig, remove: aiApi.deleteInstallationConfig,
                  test: aiApi.testInstallationModel },
};

function AIEndpointSettings({ scope }: { scope: "workspace" | "installation" }) {
  const api = API[scope];
  const workspace = scope === "workspace";
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: [api.key], queryFn: api.get });
  const status = useQuery({ queryKey: ["ai-status"], queryFn: aiApi.status, enabled: workspace });
  // A workspace with no settings of its own uses the installation's (or a global workspace's): the form only
  // opens when somebody chooses to give it its own.
  const [ownForm, setOwnForm] = useState(false);

  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [structuredModel, setStructuredModel] = useState("");
  const [modelSettings, setModelSettings] = useState<Record<string, ModelSetting>>({});
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [visionModel, setVisionModel] = useState("");
  const [asrModel, setAsrModel] = useState("");
  const [ttsModel, setTtsModel] = useState("");
  const [rerankModel, setRerankModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  // A new form is filled in to use AI: offered unless someone unticks it.
  const [enabled, setEnabled] = useState(true);
  const [allowConfidential, setAllowConfidential] = useState(false);
  const [maxOutputTokens, setMaxOutputTokens] = useState("");
  const [indexOnPublish, setIndexOnPublish] = useState(true);
  const [indexIntervalHours, setIndexIntervalHours] = useState("12");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (loaded || config.isLoading) return;
    const c = config.data;
    if (c) {
      setBaseUrl(c.base_url);
      setModel(c.model);
      setStructuredModel(c.structured_model ?? "");
      setModelSettings(c.model_settings ?? {});
      setEmbeddingModel(c.embedding_model ?? "");
      setVisionModel(c.vision_model ?? "");
      setAsrModel(c.asr_model ?? "");
      setTtsModel(c.tts_model ?? "");
      setRerankModel(c.rerank_model ?? "");
      setEnabled(c.enabled);
      setAllowConfidential(c.allow_confidential);
      setMaxOutputTokens(c.max_output_tokens ? String(c.max_output_tokens) : "");
      setIndexOnPublish(c.index_on_publish ?? true);
      setIndexIntervalHours(String(c.index_interval_hours ?? 12));
    }
    setLoaded(true);
  }, [config.data, config.isLoading, loaded]);

  const save = useMutation({
    mutationFn: () =>
      api.save({
        base_url: baseUrl.trim(),
        model: model.trim(),
        structured_model: structuredModel.trim() || null,
        model_settings: modelSettings,
        embedding_model: embeddingModel.trim() || null,
        vision_model: visionModel.trim() || null,
        asr_model: asrModel.trim() || null,
        tts_model: ttsModel.trim() || null,
        rerank_model: rerankModel.trim() || null,
        // Left out entirely when untouched, so saving a model change does
        // not wipe the stored key.
        ...(apiKey ? { api_key: apiKey } : {}),
        enabled,
        allow_confidential: allowConfidential,
        max_output_tokens: Number(maxOutputTokens) > 0 ? Math.floor(Number(maxOutputTokens)) : null,
        index_on_publish: indexOnPublish,
        index_interval_hours: Math.min(720, Math.max(0, Math.floor(Number(indexIntervalHours) || 0))),
      }),
    onSuccess: () => {
      setApiKey("");
      queryClient.invalidateQueries({ queryKey: [api.key] });
      queryClient.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });

  const check = useMutation({
    mutationFn: api.check,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.key] });
      queryClient.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });

  const saved = config.data;
  const checkResult = check.data;
  const inheriting = workspace && !saved && !config.isLoading;
  const showForm = !inheriting || ownForm;
  const backToShared = useMutation({
    mutationFn: api.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.key] });
      queryClient.invalidateQueries({ queryKey: ["ai-status"] });
      setLoaded(false);
      setOwnForm(false);
    },
  });

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold text-slate-900">{workspace ? "AI endpoint" : "AI settings for the installation"}</h1>
      <p className="mt-1 text-sm text-slate-500">
        {workspace ? <>Any OpenAI-compatible endpoint. AI features stay unavailable until a check against
          this endpoint passes, so a gateway whose key has since been rotated reads as unavailable rather than
          quietly failing.</>
          : <>The endpoint and models every workspace uses unless it sets its own on its <i>AI endpoint</i> page.
            Checked like a workspace's; until the check passes, workspaces have no shared AI. Confidential documents
            are never sent on these settings: each workspace decides that for itself.</>}
      </p>

      {!workspace && saved && !(saved.enabled && saved.last_check_ok) && (
        <div className="mt-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <span className="font-medium">Workspaces are not using these settings yet: </span>
          {!saved.enabled
            ? <>they are switched off. Tick “Offer AI features to the workspaces that use these settings”, save,
                then press <i>Check endpoint</i>.</>
            : saved.last_check_ok === false
              ? <>the last check failed{saved.last_check_error ? `: ${saved.last_check_error}` : ""}.</>
              : <>they have not been checked since they were last saved. Press <i>Check endpoint</i>.</>}
        </div>
      )}
      {!workspace && saved?.enabled && saved.last_check_ok && (
        <div className="mt-4 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          Shared with every workspace that has no AI settings of its own.
        </div>
      )}

      {inheriting && (
        <div className="mt-4 space-y-2 rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
          {status.data?.inherited_from ? (
            <p>
              This workspace uses the shared AI settings of{" "}
              <span className="font-medium">{status.data.inherited_from}</span>
              {status.data.model && <> — {status.data.model}</>}
              {status.data.has_rerank && <>, with a re-ranker</>}. Confidential documents are never sent on shared
              settings.
            </p>
          ) : (
            <p>{status.data?.reason ?? "This workspace has no AI settings of its own, and the installation has none to share (Administration → AI)."}</p>
          )}
          {!ownForm && (
            <button type="button" onClick={() => setOwnForm(true)}
                    className="rounded border border-sky-300 bg-white px-3 py-1 text-xs hover:bg-sky-100">
              Give this workspace settings of its own
            </button>
          )}
        </div>
      )}
      {workspace && saved && (
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
          This workspace uses settings of its own.
          <button type="button" disabled={backToShared.isPending}
                  onClick={() => { if (confirm("Remove this workspace's own AI settings and use the installation's?")) backToShared.mutate(); }}
                  className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
            Use the installation's settings instead
          </button>
        </div>
      )}

      {showForm && (<div className="mt-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700">Endpoint URL</label>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://ai-gateway.example.infn.it/v1"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Model</label>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="minimax-m27"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Embedding model
            </label>
            <input
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder="qwen3-embedding-8b"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-slate-500">
              Optional. Classifying and linking use embeddings where one is available —
              cheaper and steadier than a chat call per record.
            </p>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Model for structured work</label>
          <input
            value={structuredModel}
            onChange={(e) => setStructuredModel(e.target.value)}
            placeholder={model.trim() ? `The model above (${model.trim()})` : "The model above"}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            Optional. Answers that are data rather than prose — reworking a text into a document, filling a form
            from a description, drafting a ticket — come from this model. A fast one that does not reason suits
            them best; a reasoning model may think for minutes first. An intake profile's evaluated model still
            answers its own intake.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Vision model</label>
          <input
            value={visionModel}
            onChange={(e) => setVisionModel(e.target.value)}
            placeholder="gemma-4-31b-it"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            Optional, and usually a different model from the one above: a chat model
            answers “not a multimodal model” when shown a photograph. Needed to identify
            equipment from a picture.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Re-ranker model</label>
          <input
            value={rerankModel}
            onChange={(e) => setRerankModel(e.target.value)}
            placeholder="bge-reranker-v2-m3"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            Optional. Used by Ask ARGUS's search of what is written: the passages found by meaning and by words are
            put in order by how well each answers the question (served at the endpoint's /rerank). Without it, the
            search's own order stands.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Speech-to-text model
            </label>
            <input
              value={asrModel}
              onChange={(e) => setAsrModel(e.target.value)}
              placeholder="whisper-large-v3"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-slate-500">
              Optional. Used by the voice assistant on the beamline dashboards.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Text-to-speech model
            </label>
            <input
              value={ttsModel}
              onChange={(e) => setTtsModel(e.target.value)}
              placeholder="kokoro-82m"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-slate-500">
              Optional. Checked against the endpoint like the others, so a wrong
              name surfaces here and not at a microphone mid-shift.
            </p>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">
            API key{saved?.has_api_key && " (one is stored — leave blank to keep it)"}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={saved?.has_api_key ? "••••••••" : "Leave blank if the endpoint needs none"}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Output-token limit</label>
          <input
            type="number"
            min={1}
            step={1}
            value={maxOutputTokens}
            onChange={(e) => setMaxOutputTokens(e.target.value)}
            placeholder="No limit"
            className="mt-1 w-48 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            Optional: the most a single reply may use, for a gateway that bills or throttles by
            token. Empty means no limit. A reasoning model (Qwen, DeepSeek…) thinks before it
            answers, so a tight limit can leave it no room for the answer itself.
          </p>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-slate-700">Per-model settings</legend>
          <p className="text-xs text-slate-500">
            How each model is called, by the name used above ("auto" included). Temperature empty: ARGUS's default —
            0 to classify and chat, the model's own for structured answers, since at 0 a reasoning model's thinking
            can run on and on. Untick <i>Tell it not to think</i> for a model that cannot be told (it is then not
            sent), and <i>JSON mode</i> for one that does not have it. <i>Test</i> tries the row as it is, saved or not, through the saved endpoint,
            on a small extraction (no data of yours is sent).
          </p>
          <ModelSettingsEditor rows={modelSettings} onChange={setModelSettings}
                               suggestions={[model.trim(), structuredModel.trim()]}
                               test={(name, s) => api.test(name, s)} />
          {Object.keys(modelSettings).length > 0 && !saved && (
            <p className="text-xs text-amber-800">Save the settings for them to apply.</p>
          )}
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-slate-700">Keeping Ask ARGUS's knowledge index up to date</legend>
          <label className="flex items-start gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={indexOnPublish}
              onChange={(e) => setIndexOnPublish(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Index a document as soon as it is published or retired
              <span className="block text-xs text-slate-500">
                Only that document is embedded again: what has not changed is skipped.
              </span>
            </span>
          </label>
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
            <span>Refresh the whole index every</span>
            <input
              type="number"
              min={0}
              max={720}
              step={1}
              value={indexIntervalHours}
              onChange={(e) => setIndexIntervalHours(e.target.value)}
              className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <span>hours</span>
          </div>
          <p className="text-xs text-slate-500">
            Picks up everything else with text — tickets and their comments, comments on equipment,
            attached files, what an import brought in. 0 turns the timer off; the index button below
            still works.
          </p>
        </fieldset>

        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            {workspace ? "Offer AI features in this workspace" : "Offer AI features to the workspaces that use these settings"}
            <span className="block text-xs text-slate-500">
              Suggestions are always proposals — nothing is written to a record without
              somebody accepting it.
            </span>
          </span>
        </label>

        {workspace && (
        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            disabled={!workspace}
            checked={allowConfidential}
            onChange={(e) => setAllowConfidential(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            Send confidential documents too
            <span className="block text-xs text-slate-500">
              Off by default: documents marked <em>riservato</em> are skipped, because where
              their text goes is a decision worth making deliberately.
            </span>
          </span>
        </label>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={() => save.mutate()}
            disabled={!baseUrl.trim() || !model.trim() || save.isPending}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          <button
            onClick={() => check.mutate()}
            disabled={!saved || check.isPending}
            className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {check.isPending ? "Checking…" : "Check endpoint"}
          </button>
          {saved && (
            <button
              onClick={() => {
                if (confirm(workspace ? "Remove this workspace's own AI settings? It then uses the installation's."
                  : "Remove the installation's AI settings? Workspaces without their own lose AI."))
                  api.remove().then(() => {
                    queryClient.invalidateQueries({ queryKey: [api.key] });
                    queryClient.invalidateQueries({ queryKey: ["ai-status"] });
                    setLoaded(false);
                  });
              }}
              className="text-sm text-red-500 hover:text-red-700"
            >
              Remove
            </button>
          )}
        </div>

        {checkResult && (
          <div
            className={`rounded border p-3 text-sm ${
              checkResult.ok
                ? "border-green-200 bg-green-50 text-green-800"
                : "border-red-200 bg-red-50 text-red-700"
            }`}
          >
            {checkResult.ok
              ? `This endpoint answered, the key was accepted, and it serves ${model}.`
              : checkResult.error}
            {checkResult.models.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs">
                  {checkResult.models.length} model(s) offered
                </summary>
                <ul className="mt-1 space-y-0.5 text-xs">
                  {checkResult.models.map((m) => (
                    <li key={m}>
                      <button
                        type="button"
                        onClick={() => setModel(m)}
                        className="hover:underline"
                        title="Use this model"
                      >
                        {m}
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {saved && !checkResult && (
          <p className="text-xs text-slate-500">
            {saved.last_checked_at
              ? saved.last_check_ok
                ? `Checked ${new Date(saved.last_checked_at).toLocaleString()} — working.`
                : `Checked ${new Date(saved.last_checked_at).toLocaleString()} — ${saved.last_check_error}`
              : "Not checked since it was last changed."}
          </p>
        )}
      </div>)}
      {workspace && <KnowledgeIndex />}
      {workspace && <IntakeProfiles />}
    </div>
  );
}
