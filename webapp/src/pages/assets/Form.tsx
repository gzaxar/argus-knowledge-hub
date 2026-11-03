import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { assetsApi, intakeApi, schemasApi, type AssistResult } from "../../api/client";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import { AttributeFields } from "../../components/AttributeFields";
import { finalFor, GuidedEntry } from "../../components/GuidedEntry";
import { emptyAddress, emptyPort, fromProposals, macLooksRight, NetworkPortSection } from "../../components/NetworkPortSection";
import { portBody, ProposedPorts, type PortChoice } from "../../components/ProposedPorts";
import { SchemaBrowser } from "../../components/SchemaBrowser";
import { SchemaPicker } from "../../components/SchemaPicker";
import { effectiveAttributes } from "../../lib/schemaAttributes";

export function AssetForm() {
  const { uid } = useParams<{ uid: string }>();
  const isEditing = !!uid;
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const existing = useQuery({
    queryKey: ["assets", uid],
    queryFn: () => assetsApi.get(uid!),
    enabled: isEditing,
  });

  const [schemaUid, setSchemaUid] = useState(searchParams.get("schema_uid") ?? "");
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [attributes, setAttributes] = useState<Record<string, unknown>>({});
  const [isGlobal, setIsGlobal] = useState(false);
  const [assisted, setAssistedState] = useState<AssistResult | null>(null);
  const [port, setPort] = useState(emptyPort);
  const [address, setAddress] = useState(emptyAddress);
  const [ports, setPorts] = useState<PortChoice[]>([]);
  // What the assistant read for the network goes to the network section, ticked: the person may untick it.
  // The ports of a port table (a converter's serial ports) are listed apart, ticked too.
  const setAssisted = (r: AssistResult | null) => {
    setAssistedState(r);
    if (r?.companions?.length) {
      const next = fromProposals(r.companions, port, address);
      setPort(next.port);
      setAddress(next.address);
      const listed = r.companions.filter((c) => c.kind === "port" && !c.attributes.mac);
      if (listed.length) setPorts(listed.map((c) => ({ ...c.attributes, on: c.selected })));
    }
  };
  const [browsing, setBrowsing] = useState(false);
  const currentWorkspaceId = useCurrentWorkspaceId();
  const draft = { uid: uid ?? null, schema_uid: schemaUid, name, key, attributes };

  /** Values from the checklist or the assistant, by field name. */
  const apply = (values: Record<string, unknown>) => {
    for (const [field, value] of Object.entries(values)) {
      if (field === "schema_uid") setSchemaUid(String(value ?? ""));
      else if (field === "name") setName(String(value ?? ""));
      else if (field === "key") setKey(String(value ?? ""));
      else if (field.startsWith("attributes.")) {
        const k = field.slice(11);
        setAttributes((prev) => ({ ...prev, [k]: value }));
      }
    }
  };

  useEffect(() => {
    if (existing.data) {
      setSchemaUid(existing.data.schema_uid);
      setName(existing.data.name);
      setKey(existing.data.key);
      setAttributes(existing.data.attributes);
      setIsGlobal(existing.data.is_global);
    }
  }, [existing.data]);

  const objectSchemas = (schemas.data ?? []).filter((s) => (s.applies_to ?? "objects") === "objects");
  // A record moved here with a type of the workspace it came from: that type cannot be used here, so its type is
  // chosen again (the same-named one here, suggested) — the one case an edit changes a type.
  const strayType = isEditing && !!existing.data && !!schemas.data &&
    !objectSchemas.some((s) => s.uid === existing.data!.schema_uid);
  const suggested = useRef(false);
  useEffect(() => {
    if (strayType && !suggested.current) {
      suggested.current = true;
      const same = objectSchemas.find((s) => s.name === existing.data!.type && s.is_concrete !== false);
      setSchemaUid(same?.uid ?? "");
    }
  }, [strayType]);  // eslint-disable-line react-hooks/exhaustive-deps
  const schema = schemas.data?.find((s) => s.uid === schemaUid);
  const attrDefs = effectiveAttributes(schema, schemas.data);
  // A Product model chosen fills what is recorded beside it — manufacturer and model as written — where empty.
  const fillRecorded = (modelUid: string) => {
    const keys = new Set(attrDefs.map((a) => a.key ?? a.name));
    if (!keys.has("manufacturer") && !keys.has("model")) return;
    assetsApi.get(modelUid).then((m) => {
      const a = (m.attributes ?? {}) as Record<string, unknown>;
      setAttributes((prev) => ({
        ...prev,
        ...(keys.has("manufacturer") && !prev.manufacturer && a.vendor ? { manufacturer: a.vendor } : {}),
        ...(keys.has("model") && !prev.model && (a.model_code || m.name) ? { model: a.model_code ?? m.name } : {}),
      }));
    }).catch(() => undefined);
  };
  // What a blank key becomes, from the workspace's key pattern.
  const nextKey = useQuery({
    queryKey: ["asset-next-key", schemaUid],
    queryFn: () => assetsApi.nextKey(schemaUid || undefined),
    enabled: !isEditing,
  });

  // Whether the chosen type is equipment on a network (the guide decides; nothing to ask for a pump).
  const offer = useQuery({
    queryKey: ["network-port-offer", schemaUid],
    queryFn: () => intakeApi.guide("asset", { schema_uid: schemaUid }),
    enabled: !isEditing && !!schemaUid,
    staleTime: 5 * 60_000,
    select: (g) => g.network_port,
  });
  const showNetwork = !isEditing && (!!offer.data?.offered || port.fromAssistant || address.fromAssistant);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (isEditing) {
        return assetsApi.update(uid!, { name, attributes, is_global: isGlobal,
                                        ...(strayType && schemaUid ? { schema_uid: schemaUid } : {}) },
                                existing.data?.workspace_id);
      }
      return assetsApi.create({
        uid: crypto.randomUUID(),
        schema_uid: schemaUid,
        // Blank: the server makes one from the workspace's key pattern.
        key: key.trim() || undefined,
        name,
        attributes,
        is_global: isGlobal,
        ...((showNetwork && port.on && offer.data?.port_type_uid !== null) || ports.some((p) => p.on)
          ? { ports: [
              ...(showNetwork && port.on && offer.data?.port_type_uid !== null
                ? [{ port_label: port.port_label.trim() || "eth0", port_kind: port.port_kind, mac: port.mac.trim() || null }]
                : []),
              ...ports.filter((p) => p.on).map(portBody),
            ] }
          : {}),
        ...(showNetwork && address.on && (address.ip.trim() || address.hostname.trim())
          ? { addresses: [{ ip: address.ip.trim() || null, hostname: address.hostname.trim() || null }] }
          : {}),
      });
    },
    onSuccess: async (asset) => {
      // Which suggestions were kept or corrected: provenance, never a blocker.
      if (assisted) {
        await intakeApi.outcome(assisted.run_id, asset!.uid, finalFor(assisted, draft)).catch(() => undefined);
      }
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["asset-next-key"] });
      navigate(`/assets/${asset!.uid}`);
    },
  });

  return (
    <div className="max-w-6xl">
      <h1 className="text-2xl font-semibold text-slate-900">
        {isEditing ? "Edit asset" : "New asset"}
      </h1>
      {!isEditing && (
        <p className="mt-1 text-sm text-slate-500">
          Describe it or photograph its nameplate, and the form fills itself; the checklist keeps the entry correct.
        </p>
      )}

      <div className="mt-2 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          saveMutation.mutate();
        }}
        className="mt-6 space-y-5"
      >
        <div>
          <div className="flex items-baseline justify-between">
            <label className="block text-sm font-medium text-slate-700">Type</label>
            {!isEditing && (
              <button
                type="button"
                onClick={() => setBrowsing(true)}
                className="text-xs text-indigo-600 hover:underline"
              >
                Browse all types
              </button>
            )}
          </div>
          <div className="mt-1">
            <SchemaPicker
              schemas={objectSchemas}
              value={schemaUid}
              onChange={(uid) => setSchemaUid(uid)}
              currentWorkspaceId={currentWorkspaceId}
              selectable={(s) => s.is_concrete !== false}
              placeholder="Type to search, e.g. ion pump, power supply…"
              inputClassName="w-full rounded border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"
              disabled={isEditing && !strayType}
            />
          </div>
          {strayType ? (
            <p role="status" className="mt-1 text-xs text-amber-800">
              Its type, {existing.data?.type}, belongs to the workspace it came from and cannot be used here: choose
              this workspace&apos;s{objectSchemas.some((s) => s.name === existing.data?.type) ? " (the same type here is suggested)" : ""}.
            </p>
          ) : (
            <p className="mt-1 text-xs text-slate-500">
              What kind of thing it is. The type decides the attributes below.
            </p>
          )}
          {browsing && (
            <SchemaBrowser
              schemas={objectSchemas}
              onPick={(s) => {
                setSchemaUid(s.uid);
                setBrowsing(false);
              }}
              onClose={() => setBrowsing(false)}
            />
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">
            Key {!isEditing && <span className="font-normal text-slate-400">(optional)</span>}
          </label>
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            disabled={isEditing}
            placeholder={nextKey.data ? `${nextKey.data.key}, made when you save` : "Made when you save"}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm disabled:bg-slate-100"
          />
          <p className="mt-1 text-xs text-slate-500">
            {isEditing
              ? "A key does not change once given: labels and links carry it."
              : "Leave it blank for the next key of this workspace, or type the identifier on its label."}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="is_global"
            checked={isGlobal}
            onChange={(e) => setIsGlobal(e.target.checked)}
          />
          <label htmlFor="is_global" className="text-sm text-slate-700">
            Global — visible and referenceable from every workspace (for what is meant to be shared: models, vendors, people, companies). Otherwise it stays in this workspace.
          </label>
        </div>

        {attrDefs.length > 0 && (
          <div>
            <label className="block text-sm font-medium text-slate-700">Attributes</label>
            <div className="mt-2 rounded border border-slate-200 p-3">
              <AttributeFields attrs={attrDefs} values={attributes} onChange={(k, v) => {
                setAttributes((prev) => ({ ...prev, [k]: v }));
                if (k === "product_model" && typeof v === "string" && v) fillRecorded(v);
              }} />
            </div>
          </div>
        )}

        {showNetwork && (
          <NetworkPortSection port={port} setPort={setPort} address={address} setAddress={setAddress}
                              addressAvailable={!!offer.data?.address_type_uid || address.fromAssistant} />
        )}
        {!isEditing && (
          <ProposedPorts ports={ports}
                         onToggle={(i, on) => setPorts((all) => all.map((p, j) => (j === i ? { ...p, on } : p)))} />
        )}

        <button
          type="submit"
          disabled={saveMutation.isPending || !schemaUid || (port.on && !macLooksRight(port.mac))}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {saveMutation.isPending ? "Saving…" : "Save asset"}
        </button>
        {saveMutation.isError && (
          <p className="text-sm text-red-600">{(saveMutation.error as Error).message}</p>
        )}
      </form>
      </div>
      <aside className="lg:sticky lg:top-4 lg:self-start">
        <GuidedEntry kind="asset" draft={draft} onApply={apply} onAssist={setAssisted} />
      </aside>
      </div>
    </div>
  );
}
