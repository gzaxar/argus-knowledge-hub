import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, assetsApi, attributeValuesApi, catalogueCollectionsApi, directoryApi, membersApi, schemasApi } from "../api/client";
import { SchemaAttribute } from "../api/types";
import { AssetPicker } from "./AssetPicker";
import { IndexedStringInput } from "./IndexedStringInput";
import { LabelInput } from "./LabelInput";
import { findOption } from "../lib/schemaAttributes";
import { UserPicker } from "./UserPicker";

/** Which kind of record the attribute is being edited on — the vocabulary
 * of an indexed attribute is read per kind, since "Components" on a ticket
 * and on an object are different lists. */
export type AppliesTo = "objects" | "tickets" | "documents";

function useVocabulary(appliesTo: AppliesTo, attribute: SchemaAttribute) {
  const key = attribute.key ?? attribute.name;
  return useQuery({
    queryKey: ["attribute-values", appliesTo, key],
    queryFn: () => attributeValuesApi.list(appliesTo, key),
    enabled: !!attribute.indexed && !!key,
    staleTime: 30_000,
  });
}

function descendantSchemaUids(allSchemas: { uid: string; parent_schema_uid: string | null }[], rootUid: string): Set<string> {
  const children = new Map<string, string[]>();
  for (const s of allSchemas) {
    if (s.parent_schema_uid) {
      children.set(s.parent_schema_uid, [...(children.get(s.parent_schema_uid) ?? []), s.uid]);
    }
  }
  const result = new Set<string>();
  const stack = [rootUid];
  while (stack.length > 0) {
    const current = stack.pop()!;
    for (const child of children.get(current) ?? []) {
      if (!result.has(child)) {
        result.add(child);
        stack.push(child);
      }
    }
  }
  return result;
}

function UserInput({
  value,
  onChange,
  disabled,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}) {
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory });
  return (
    <UserPicker
      members={members.data ?? []}
      value={typeof value === "string" ? value : null}
      onChange={onChange}
      disabled={disabled || members.isLoading}
      placeholder={members.isLoading ? "Loading…" : "Search members…"}
    />
  );
}

/** A group: a service or team, from the directory or made here. Groups are organisation-wide. */
function GroupInput({
  value,
  onChange,
  disabled,
  base,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  base: string;
}) {
  const groups = useQuery({ queryKey: ["directory-groups"], queryFn: () => directoryApi.groups() });
  return (
    <select
      className={base}
      disabled={disabled || groups.isLoading}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">{groups.isLoading ? "Loading…" : "— none —"}</option>
      {(groups.data ?? []).map((g) => (
        <option key={g.uid} value={g.uid}>
          {g.name}
          {g.source === "local" ? "" : ` (${g.source})`}
        </option>
      ))}
    </select>
  );
}

function CurrentUserInput({ value, base }: { value: unknown; base: string }) {
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory });
  const member = members.data?.find((m) => m.user_id === value);
  const label = value ? member?.name || member?.email || String(value) : "— set automatically —";
  return (
    <input
      className={`${base} bg-slate-100 text-slate-500`}
      disabled
      readOnly
      value={label}
      title="Set automatically to whoever creates or last edits this record"
    />
  );
}

function ReferenceInput({
  attribute,
  value,
  onChange,
  disabled,
  base,
}: {
  attribute: SchemaAttribute;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  base: string;
}) {
  const allSchemas = useQuery({
    queryKey: ["schemas"],
    queryFn: schemasApi.list,
    enabled: !!attribute.includeChildren,
  });
  // A product model is searched (installed models, then the library) rather than listed: there may be thousands.
  const isModel = attribute.referenceType === "Product Model" || attribute.key === "product_model";
  const targets = useQuery({
    queryKey: ["assets", attribute.referenceSchemaUid],
    queryFn: () => assetsApi.list(attribute.referenceSchemaUid),
    enabled: !!attribute.referenceSchemaUid && !attribute.includeChildren && !isModel,
  });
  const allAssets = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.list(),
    enabled: !!attribute.referenceSchemaUid && !!attribute.includeChildren,
  });

  if (isModel && attribute.referenceSchemaUid) {
    return <ModelPicker value={typeof value === "string" ? value : null} onChange={onChange} disabled={disabled} base={base} />;
  }

  if (!attribute.referenceSchemaUid) {
    // Legacy attribute with only a display label, no linked schema — fall
    // back to entering the target uid directly.
    return (
      <input
        className={base}
        disabled={disabled}
        placeholder="Asset uid"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  let options = targets.data;
  if (attribute.includeChildren && allAssets.data) {
    const allowed = descendantSchemaUids(allSchemas.data ?? [], attribute.referenceSchemaUid);
    allowed.add(attribute.referenceSchemaUid);
    options = allAssets.data.filter((a) => allowed.has(a.schema_uid));
  }
  const isLoading = attribute.includeChildren
    ? allSchemas.isLoading || allAssets.isLoading
    : targets.isLoading;

  const picker = (
    <AssetPicker
      options={options ?? []}
      value={typeof value === "string" ? value : null}
      onChange={onChange}
      disabled={disabled || isLoading}
      placeholder={isLoading ? "Loading…" : "Search assets…"}
    />
  );
  if (attribute.key !== "vendor_ref" || disabled) return picker;
  return <div className="space-y-1">{picker}<AddVendor onAdded={onChange} base={base} /></div>;
}

/** A Product Model's vendor not listed yet: added to the catalogue by name (one going by that name or alias is
 *  chosen instead), so a model never needs its company written as text. */
function AddVendor({ onAdded, base }: { onAdded: (uid: string) => void; base: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => catalogueCollectionsApi.addVendor(name.trim()),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      onAdded(r.uid);
      setName("");
      setOpen(false);
    },
  });
  if (!open) {
    return <button type="button" className="text-xs text-sky-800 underline" onClick={() => setOpen(true)}>Not listed? Add a vendor</button>;
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input className={`${base} max-w-xs`} aria-label="New vendor's name" placeholder="The company's name" value={name}
             onChange={(e) => setName(e.target.value)} />
      <button type="button" className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
              disabled={!name.trim() || add.isPending} onClick={() => add.mutate()}>
        {add.isPending ? "Adding…" : "Add"}
      </button>
      {add.isError && <span className="text-xs text-red-600">{installProblem(add.error)}</span>}
    </div>
  );
}

function installProblem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (d && typeof d === "object" && "error" in d) return String((d as { error: string }).error);
    if (typeof d === "string") return d;
    if (e.status === 403) return "you may not create records here";
  }
  return "no answer from ARGUS";
}

/** A unit's product model: typed, searched — the catalogue's models first, then the library of its sources (the
 *  NetBox Device Type Library among them) — and a library model installed in the catalogue when it is chosen.
 *  The models of this workspace's domains, unless every model is asked for. */
export function ModelPicker({ value, onChange, disabled, base }: {
  value: string | null; onChange: (value: unknown) => void; disabled: boolean; base: string;
}) {
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState("");
  const [every, setEvery] = useState(false);
  const [lookAlike, setLookAlike] = useState<{ uid: string; name: string; message: string } | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setQ(typed.trim()), 250);
    return () => clearTimeout(t);
  }, [typed]);
  const current = useQuery({ queryKey: ["assets", value], queryFn: () => assetsApi.get(value!), enabled: !!value });
  const found = useQuery({ queryKey: ["model-search", q, every], queryFn: () => catalogueCollectionsApi.searchModels(q, every),
                           enabled: q.length >= 2, placeholderData: (previous) => previous });
  const install = useMutation({
    mutationFn: (catalogueId: string) => catalogueCollectionsApi.installOne(catalogueId),
    onSuccess: (r) => { setLookAlike(null); setTyped(""); onChange(r.uid); },
    onError: (e) => {
      const d = (e instanceof ApiError ? (e.body as { detail?: { candidate?: { uid: string; name: string }; error?: string } })?.detail : null);
      if (d?.candidate) setLookAlike({ ...d.candidate, message: d.error ?? "" });
    },
  });
  const pick = (uid: string) => { setLookAlike(null); setTyped(""); onChange(uid); };
  const results = q.length >= 2 ? found.data : undefined;
  return (
    <div className="space-y-1">
      {value && (
        <p className="text-sm">
          <span className="font-medium">{current.data?.name ?? value}</span>
          {current.data?.key && <span className="ml-1 font-mono text-xs text-slate-400">{current.data.key}</span>}
          {!disabled && <button type="button" onClick={() => onChange(null)} className="ml-2 text-xs text-slate-500 underline">clear</button>}
        </p>
      )}
      {!disabled && (
        <>
          <input className={base} value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Search a product model"
                 placeholder={value ? "Search another model: its code, as on the label…" : "Search a model: its code, as on the label…"} />
          {results && (
            <ul role="listbox" aria-label="Product models" className="max-h-64 overflow-y-auto rounded border border-slate-200 bg-white text-sm">
              {results.installed.map((m) => (
                <li key={m.uid}>
                  <button type="button" role="option" aria-selected={m.uid === value} onClick={() => pick(m.uid)}
                          className="flex w-full items-baseline justify-between gap-2 px-2 py-1 text-left hover:bg-slate-50">
                    <span>{m.name}{m.model_code && <span className="ml-1 font-mono text-xs text-slate-500">{m.model_code}</span>}</span>
                    <span className="shrink-0 text-xs text-slate-400">in the catalogue</span>
                  </button>
                </li>
              ))}
              {results.library.map((m) => (
                <li key={m.catalogue_id}>
                  <button type="button" role="option" aria-selected={false} disabled={install.isPending}
                          onClick={() => install.mutate(m.catalogue_id)}
                          className="flex w-full items-baseline justify-between gap-2 px-2 py-1 text-left hover:bg-slate-50 disabled:opacity-50">
                    <span>{m.name}{m.part_number && <span className="ml-1 font-mono text-xs text-slate-500">{m.part_number}</span>}</span>
                    <span className="shrink-0 text-xs text-sky-700">{m.source === "netbox" ? "NetBox" : "collection"} · add</span>
                  </button>
                </li>
              ))}
              {results.installed.length === 0 && results.library.length === 0 && (
                <li className="px-2 py-1 text-slate-500">No model matches “{q}”.</li>
              )}
              {results.more && <li className="px-2 py-1 text-xs text-slate-400">More match: type more of the code.</li>}
            </ul>
          )}
          <label className="flex items-center gap-1 text-xs text-slate-500">
            <input type="checkbox" checked={every} onChange={(e) => setEvery(e.target.checked)} />
            every model, not only this workspace's domains
          </label>
          {install.isPending && <p className="text-xs text-slate-500">Adding it to the catalogue…</p>}
          {lookAlike && (
            <p role="alert" className="text-xs text-amber-800">
              {lookAlike.message}{" "}
              <button type="button" onClick={() => pick(lookAlike.uid)} className="font-medium underline">Use {lookAlike.name}</button>
            </p>
          )}
          {install.isError && !lookAlike && (
            <p role="alert" className="text-xs text-red-600">
              It could not be added to the catalogue: {installProblem(install.error)}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function IndexedInput({
  attribute,
  appliesTo,
  value,
  onChange,
  disabled,
  base,
}: {
  attribute: SchemaAttribute;
  appliesTo: AppliesTo;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  base: string;
}) {
  const vocabulary = useVocabulary(appliesTo, attribute);
  return (
    <IndexedStringInput
      value={typeof value === "string" ? value : value == null ? "" : String(value)}
      onChange={onChange}
      suggestions={vocabulary.data ?? []}
      disabled={disabled}
      loading={vocabulary.isLoading}
      className={base}
    />
  );
}

function SingleAttributeInput({
  attribute,
  appliesTo,
  value,
  onChange,
  disabled,
}: {
  attribute: SchemaAttribute;
  appliesTo: AppliesTo;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}) {
  const base =
    "w-full rounded border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-100";

  // An indexed string is a key: offer what the workspace already uses
  // rather than an empty box that invites a fourth spelling.
  if (attribute.indexed && (attribute.type === "string" || !attribute.type)) {
    return (
      <IndexedInput
        attribute={attribute}
        appliesTo={appliesTo}
        value={value}
        onChange={onChange}
        disabled={disabled}
        base={base}
      />
    );
  }

  switch (attribute.type) {
    case "boolean":
      return (
        <input
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4"
        />
      );
    case "integer":
    case "float":
      return (
        <input
          type="number"
          step={attribute.type === "float" ? "any" : 1}
          className={base}
          disabled={disabled}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      );
    case "date":
      return (
        <input
          type="date"
          className={base}
          disabled={disabled}
          value={typeof value === "string" ? value.slice(0, 10) : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "datetime":
      return (
        <input
          type="datetime-local"
          className={base}
          disabled={disabled}
          value={typeof value === "string" ? value.slice(0, 16) : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "text":
      return (
        <textarea
          className={base}
          rows={3}
          disabled={disabled}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "enumeration": {
      // A proposed answer may name its option by id: it is shown, and saved, as the option's value.
      const chosen = findOption(attribute.options, value);
      const current = chosen ? chosen.value : typeof value === "string" ? value : "";
      return (
        <select
          className={base}
          disabled={disabled}
          value={current}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">—</option>
          {(attribute.options ?? []).map((opt) => (
            <option key={opt.id} value={opt.value}>
              {opt.value}
            </option>
          ))}
          {current && !chosen && <option value={current}>{current} (not in the current list)</option>}
        </select>
      );
    }
    case "reference":
      return (
        <ReferenceInput
          attribute={attribute}
          value={value}
          onChange={onChange}
          disabled={disabled}
          base={base}
        />
      );
    case "user":
      return <UserInput value={value} onChange={onChange} disabled={disabled} />;
    case "group":
      return <GroupInput value={value} onChange={onChange} disabled={disabled} base={base} />;
    case "current_user":
      return <CurrentUserInput value={value} base={base} />;
    default:
      return (
        <input
          className={base}
          disabled={disabled}
          value={typeof value === "string" ? value : value == null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}

export function AttributeInput({
  attribute,
  value,
  onChange,
  appliesTo = "objects",
}: {
  attribute: SchemaAttribute;
  value: unknown;
  onChange: (value: unknown) => void;
  appliesTo?: AppliesTo;
}) {
  const disabled = attribute.readOnly ?? false;

  if (!attribute.multiValue) {
    return (
      <SingleAttributeInput
        attribute={attribute}
        appliesTo={appliesTo}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    );
  }

  // Several keys at once read as chips, not as a column of text boxes with
  // an "+ Add value" button — components or keywords are a set, and adding
  // the fifth one should cost one keystroke.
  if (attribute.indexed && (attribute.type === "string" || !attribute.type)) {
    return (
      <IndexedMultiInput
        attribute={attribute}
        appliesTo={appliesTo}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    );
  }

  const values = Array.isArray(value) ? value : [];
  const atMax =
    attribute.maxCardinality !== undefined && values.length >= attribute.maxCardinality;

  return (
    <div className="space-y-1.5">
      {values.map((v, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <div className="flex-1">
            <SingleAttributeInput
              attribute={attribute}
              appliesTo={appliesTo}
              value={v}
              onChange={(nv) => {
                const next = [...values];
                next[i] = nv;
                onChange(next);
              }}
              disabled={disabled}
            />
          </div>
          {!disabled && (
            <button
              type="button"
              onClick={() => onChange(values.filter((_, idx) => idx !== i))}
              className="text-xs text-red-500 hover:text-red-700"
            >
              Remove
            </button>
          )}
        </div>
      ))}
      {!disabled && !atMax && (
        <button
          type="button"
          onClick={() => onChange([...values, null])}
          className="text-xs text-slate-600 hover:text-slate-900"
        >
          + Add value
        </button>
      )}
      {(attribute.minCardinality !== undefined || attribute.maxCardinality !== undefined) && (
        <p className="text-[11px] text-slate-400">
          {attribute.minCardinality !== undefined && `min ${attribute.minCardinality}`}
          {attribute.minCardinality !== undefined && attribute.maxCardinality !== undefined && " · "}
          {attribute.maxCardinality !== undefined && `max ${attribute.maxCardinality}`}
        </p>
      )}
    </div>
  );
}

function IndexedMultiInput({
  attribute,
  appliesTo,
  value,
  onChange,
  disabled,
}: {
  attribute: SchemaAttribute;
  appliesTo: AppliesTo;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}) {
  const vocabulary = useVocabulary(appliesTo, attribute);
  const values = Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

  if (disabled) {
    return (
      <p className="text-sm text-slate-500">{values.length ? values.join(", ") : "—"}</p>
    );
  }
  return (
    <LabelInput
      value={values}
      onChange={onChange}
      suggestions={vocabulary.data ?? []}
      placeholder={vocabulary.isLoading ? "Loading…" : `Add ${attribute.name.toLowerCase()}…`}
      noun="values"
    />
  );
}
