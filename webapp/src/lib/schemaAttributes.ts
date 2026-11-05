import { AppSchema, SchemaAttribute } from "../api/types";

/** A schema's own attributes plus everything inherited from its ancestor
 * chain (root-most first). A child redefining an ancestor's key overrides it
 * in place rather than duplicating it — mirrors the backend's
 * `effective_attributes` used for validation, so what you see here is what
 * gets enforced on save. */
export function effectiveAttributes(
  schema: Pick<AppSchema, "uid" | "attributes" | "parent_schema_uid"> | undefined,
  allSchemas: AppSchema[] | undefined,
): SchemaAttribute[] {
  if (!schema) return [];
  const byUid = new Map((allSchemas ?? []).map((s) => [s.uid, s]));

  const chain: (typeof schema)[] = [];
  const seen = new Set<string>();
  let current: typeof schema | undefined = schema;
  while (current && !seen.has(current.uid)) {
    chain.push(current);
    seen.add(current.uid);
    current = current.parent_schema_uid ? byUid.get(current.parent_schema_uid) : undefined;
  }
  chain.reverse();

  const merged = new Map<string, SchemaAttribute>();
  for (const s of chain) {
    for (const attr of s.attributes) {
      const key = attr.key ?? attr.name;
      if (key) merged.set(key, attr);
    }
  }
  return Array.from(merged.values());
}

/** A Product Model has one vendor: the Vendor record it points at. The type's text `vendor` is that record's name
 *  (kept by the server for search and imports), so a form offers only the reference, called Vendor. A page shows the
 *  reference, or the text of an older record not linked yet. */
export function oneVendorField(attrs: SchemaAttribute[], values: Record<string, unknown>,
                               mode: "form" | "page"): SchemaAttribute[] {
  const keys = new Set(attrs.map((a) => a.key ?? a.name));
  if (!keys.has("vendor") || !keys.has("vendor_ref")) return attrs;
  const text = values.vendor ? String(values.vendor) : "";
  const showText = mode === "page" && !values.vendor_ref && !!text;
  return attrs
    .filter((a) => (a.key ?? a.name) !== (showText ? "vendor_ref" : "vendor"))
    .map((a) => (a.key ?? a.name) !== "vendor_ref" ? a : {
      ...a, name: "Vendor",
      ...(mode === "form" && !values.vendor_ref && text
        ? { description: `“${text}” is not linked to a vendor record yet: choose it, or add it.` } : {}),
    });
}

/** Which of a schema's effective attributes came from an ancestor rather
 * than being defined locally — used to badge them as "(inherited)" in the UI. */
export function inheritedKeys(
  schema: Pick<AppSchema, "attributes"> | undefined,
  effective: SchemaAttribute[],
): Set<string> {
  const ownKeys = new Set((schema?.attributes ?? []).map((a) => a.key ?? a.name));
  return new Set(effective.filter((a) => !ownKeys.has(a.key ?? a.name)).map((a) => a.key ?? a.name));
}

/** The option a stored or proposed enumeration answer names: by its value (what is stored) or by its id (what
 * the assistant and packages call it), in any case — as the server's attribute_validation.choice_value. */
export function findOption<T extends { id: string; value: string }>(options: T[] | null | undefined, answer: unknown): T | undefined {
  if (answer == null || answer === "") return undefined;
  const text = String(answer).trim().toLowerCase();
  return (options ?? []).find((o) => String(o.value).toLowerCase() === text || String(o.id).toLowerCase() === text);
}
