import { useQuery } from "@tanstack/react-query";
import { assetsApi } from "../api/client";
import { SchemaAttribute } from "../api/types";
import { isLive } from "../lib/liveRecords";
import { FilterValue } from "./AttributeFilters";

export function AttributeFilterInput({
  attribute,
  value,
  onChange,
}: {
  attribute: SchemaAttribute;
  value: FilterValue;
  onChange: (value: FilterValue) => void;
}) {
  const base = "rounded border border-slate-300 px-2 py-1 text-sm";

  if (value.kind === "range") {
    return (
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          placeholder="min"
          value={value.min ?? ""}
          onChange={(e) =>
            onChange({ ...value, min: e.target.value === "" ? undefined : Number(e.target.value) })
          }
          className={`${base} w-20`}
        />
        <span className="text-xs text-slate-400">&ndash;</span>
        <input
          type="number"
          placeholder="max"
          value={value.max ?? ""}
          onChange={(e) =>
            onChange({ ...value, max: e.target.value === "" ? undefined : Number(e.target.value) })
          }
          className={`${base} w-20`}
        />
      </div>
    );
  }

  if (value.kind === "bool") {
    return (
      <select
        value={value.value ? "yes" : "no"}
        onChange={(e) => onChange({ kind: "bool", value: e.target.value === "yes" })}
        className={base}
      >
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    );
  }

  if (value.kind === "dateRange") {
    return (
      <div className="flex items-center gap-1.5">
        <input
          type="date"
          value={value.from ?? ""}
          onChange={(e) => onChange({ ...value, from: e.target.value || undefined })}
          className={base}
        />
        <span className="text-xs text-slate-400">&ndash;</span>
        <input
          type="date"
          value={value.to ?? ""}
          onChange={(e) => onChange({ ...value, to: e.target.value || undefined })}
          className={base}
        />
      </div>
    );
  }

  if (value.kind === "in" && attribute.type === "enumeration") {
    const options = attribute.options ?? [];
    return (
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const checked = value.values.includes(opt.value);
          return (
            <label key={opt.id} className="flex items-center gap-1 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) =>
                  onChange({
                    kind: "in",
                    values: e.target.checked
                      ? [...value.values, opt.value]
                      : value.values.filter((v) => v !== opt.value),
                  })
                }
              />
              {opt.value}
            </label>
          );
        })}
        {options.length === 0 && <span className="text-xs text-slate-400">No choices configured.</span>}
      </div>
    );
  }

  if (value.kind === "in" && attribute.type === "reference") {
    return <ReferenceFilterSelect attribute={attribute} value={value} onChange={onChange} />;
  }

  return (
    <input
      type="text"
      value={value.kind === "text" ? value.value : ""}
      onChange={(e) => onChange({ kind: "text", value: e.target.value })}
      placeholder="contains…"
      className={`${base} w-full`}
    />
  );
}

function ReferenceFilterSelect({
  attribute,
  value,
  onChange,
}: {
  attribute: SchemaAttribute;
  value: Extract<FilterValue, { kind: "in" }>;
  onChange: (value: FilterValue) => void;
}) {
  const targets = useQuery({
    queryKey: ["assets", attribute.referenceSchemaUid],
    queryFn: () => assetsApi.list(attribute.referenceSchemaUid),
    enabled: !!attribute.referenceSchemaUid,
  });

  return (
    <select
      multiple
      value={value.values}
      onChange={(e) =>
        onChange({
          kind: "in",
          values: Array.from(e.target.selectedOptions, (o) => o.value),
        })
      }
      className="h-20 rounded border border-slate-300 px-2 py-1 text-sm"
    >
      {targets.data?.filter((a) => isLive(a) || value.values.includes(a.uid)).map((a) => (
        <option key={a.uid} value={a.uid}>
          {a.name} ({a.key})
        </option>
      ))}
    </select>
  );
}
