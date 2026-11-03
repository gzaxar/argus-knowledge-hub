import type { SchemaAttribute } from "../api/types";
import { AttributeInput } from "./AttributeInput";

const GROUP_NAMES: Record<string, string> = {
  PBS: "Product breakdown (PBS)",
  recorded: "As recorded — on the label, or by the import",
};

export const empty = (v: unknown) => v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
const keyOf = (a: SchemaAttribute) => a.key ?? a.name;

type Block = { group: null; attrs: SchemaAttribute[] } | { group: string; attrs: SchemaAttribute[] };

/** The order a form shows fields in: as the type defines them, except that what was recorded about a unit's
 *  model (manufacturer, model as written) follows its Product model, the catalogue's. */
export function orderedFields(attrs: SchemaAttribute[]): SchemaAttribute[] {
  const model = attrs.findIndex((a) => keyOf(a) === "product_model");
  if (model < 0) return attrs;
  const recorded = attrs.filter((a) => a.group === "recorded");
  const rest = attrs.filter((a) => a.group !== "recorded");
  const at = rest.findIndex((a) => keyOf(a) === "product_model");
  return [...rest.slice(0, at + 1), ...recorded, ...rest.slice(at + 1)];
}

/** Consecutive fields of one group as one block; the rest one by one. */
export function blocks(attrs: SchemaAttribute[]): Block[] {
  const out: Block[] = [];
  for (const a of attrs) {
    const last = out[out.length - 1];
    if (a.group && last && last.group === a.group) last.attrs.push(a);
    else if (a.group) out.push({ group: a.group, attrs: [a] });
    else if (last && last.group === null) last.attrs.push(a);
    else out.push({ group: null, attrs: [a] });
  }
  return out;
}

function Field({ attr, value, onChange }: { attr: SchemaAttribute; value: unknown; onChange: (v: unknown) => void }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-500">
        {attr.name}
        {attr.required && <span className="text-red-500"> *</span>}
      </label>
      {attr.description && <p className="text-[11px] text-slate-400">{attr.description}</p>}
      <div className="mt-1">
        <AttributeInput attribute={attr} value={value} onChange={onChange} />
      </div>
    </div>
  );
}

/** A record's fields, as a form shows them: grouped fields (the PBS naming, what was recorded beside the
 *  catalogue's model) folded together while empty — open when one has a value, or is required. */
export function AttributeFields({ attrs, values, onChange }: {
  attrs: SchemaAttribute[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const hasModel = !empty(values.product_model);
  return (
    <div className="space-y-3">
      {blocks(orderedFields(attrs)).map((b, i) => {
        const fields = b.attrs.map((a) => (
          <Field key={keyOf(a)} attr={a} value={values[keyOf(a)]} onChange={(v) => onChange(keyOf(a), v)} />
        ));
        if (b.group === null) return <div key={i} className="space-y-3">{fields}</div>;
        const filled = b.attrs.filter((a) => !empty(values[keyOf(a)])).length;
        const open = b.attrs.some((a) => a.required) || (filled > 0 && !(b.group === "recorded" && hasModel));
        return (
          <details key={`${b.group}-${i}`} open={open} className="rounded border border-slate-100 bg-slate-50/60 p-2">
            <summary className="cursor-pointer text-xs font-medium text-slate-600">
              {GROUP_NAMES[b.group] ?? b.group}
              <span className="ml-1 font-normal text-slate-400">
                {filled > 0 ? `${filled} of ${b.attrs.length} filled` : `${b.attrs.length} fields, empty`}
              </span>
            </summary>
            <div className="mt-2 space-y-3">{fields}</div>
          </details>
        );
      })}
    </div>
  );
}
