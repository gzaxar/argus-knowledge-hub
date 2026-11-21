/** What a failed line of an import's dry run or reconciliation means, and what to do about it — shown when the red
 * item is clicked (ImportDetail.tsx). Plain text: the page renders it, nothing here is HTML. */

export interface Explanation {
  title: string;
  what: string;
  why?: string[];
  todo?: string[];
}

const ACCEPT = "Run the dry run again with Projections set to \"accept what this release rebuilds\" (Decisions for the dry run).";

const FIELD_HINTS: [RegExp, string][] = [
  [/^site_shared$/, "site_shared says a site's place is visible from its facilities. It is derived from the place's type; the archive's value is copied (fixed in 1.35.132)."],
  [/^(name|type|schema_uid|record_status|merged_into_uid)$/,
    "The ledger writes this field from claims and decisions. Where two confirmed decisions disagree, or the source changed it outside the ledger, this release rebuilds another value."],
  [/^attributes\./, "An attribute. When a claim or a decision names it, the ledger rebuilds it from them, and a value the source wrote outside the ledger is replaced."],
  [/^email_domains$/, "A column added after the archive's release; an empty one here counts as equal (fixed in 1.35.132)."],
  [/^(created_at|updated_at)$/, "A timestamp of this instance, not of the archive."],
];

export function familyExplanation(name: string, v: { mismatch_count: number; rows: number; expected_rows: number;
    mismatches: { key: string; missing: boolean; fields: string[] }[] }): Explanation {
  const fields = Array.from(new Set(v.mismatches.flatMap((m) => m.fields)));
  const missing = v.mismatches.filter((m) => m.missing).length;
  const why: string[] = [];
  if (v.rows !== v.expected_rows) why.push(`${v.rows} rows here against ${v.expected_rows} in the archive: some were left out or loaded twice.`);
  if (missing) why.push(`${missing} of the rows shown are not here at all: a reference neither here nor in the archive kept them out.`);
  for (const f of fields) {
    const hint = FIELD_HINTS.find(([re]) => re.test(f));
    why.push(`${f}: ${hint ? hint[1] : "loaded with another value than the archive's."}`);
  }
  const ledger = fields.length > 0 && fields.every((f) => /^(name|type|schema_uid|record_status|merged_into_uid|attributes\.)/.test(f));
  return {
    title: `${name}: ${v.mismatch_count} row(s) differ`,
    what: "An authoritative family is compared row by row with the archive: each row loaded here must be exactly the archive's. " +
      "Finalization is blocked while one differs, because the archive's signature covers those rows.",
    why,
    todo: ledger && name === "assets"
      ? ["These are fields the ledger projects onto a record.", ACCEPT,
         "Accepted only on records the ledger manages; every other difference still blocks."]
      : ["Open the keys listed below the tables. If the difference is this release's and not the archive's, report it: the importer needs a fix."],
  };
}

const PROJECTIONS: Record<string, { what: string; why: string[] }> = {
  p_conflicts: {
    what: "Open conflicts: two confirmed decisions or two sources disagreeing on a fact, and identity candidates (two records holding the same MAC, serial…).",
    why: ["This release detects conflicts the source's release did not (identity candidates by MAC, confirmed against confirmed).",
      "They are not lost: after finalization they wait in the review queue."],
  },
  p_fact_state: {
    what: "For each fact of each record, which claim or decision is in effect and which are outranked or superseded.",
    why: ["The source's projection was stale, or the two releases settle a tie differently (two confirmed decisions on the same name)."],
  },
  p_derived_relations: {
    what: "Relations the ledger makes: projected from claims (projector/1) and derived by rules (located in, realized by, drives).",
    why: ["The same edge stated in the ledger and derived from an attribute is kept once in later releases: here it is the ledger's, at the source the derived one.",
      "Relations of records with no ledger facts are kept as the source had them (the Kept line)."],
  },
  p_ticket_links: {
    what: "A ticket's links to the records it involves, derived from the ticket and the Installations at the time of the incident.",
    why: ["Installations or a ticket's incident range resolve differently here; a link derived from a relation the source lacked."],
  },
  p_stream_heads: {
    what: "The parsed and published head of each source stream, replayed from its revision events.",
    why: ["A revision event missing or out of order in the archive."],
  },
  p_identity_bindings: {
    what: "Which record each external source reference is bound to, replayed from identity events.",
    why: ["An identity event missing or out of order in the archive."],
  },
};

export function projectionExplanation(name: string, v: { exported: number; rebuilt: number }): Explanation {
  const p = PROJECTIONS[name];
  return {
    title: `${name}: rebuilt here ${v.rebuilt}, exported ${v.exported}`,
    what: (p?.what ?? "A projection: derived from the ledger, never loaded from the archive.") +
      " The import rebuilds it from the archive's ledger and compares it with what the source had.",
    why: [...(p?.why ?? []), "An archive from an older release was projected by older rules; one with stale projections at the source differs too."],
    todo: [ACCEPT, "The differences are listed in the signed reconciliation; new conflicts stay open for review."],
  };
}

const INVARIANTS: Record<string, string> = {
  "I-INS-1": "An Installation's interval is consistent (it does not end before it starts).",
  "I-INS-2": "A position has at most one current confirmed Installation at a time.",
  "I-INS-3": "A unit is installed at most at one position at a time.",
  "I-INS-4": "An Installation is installed at an installable position and is an installation of Equipment (its two ledger relations).",
  "I-TKT-3": "A ticket's derived links are what the derivation makes now.",
  uniqueness: "An identifier (QR code, serial, MAC…) is held by one record only.",
};

export function invariantExplanation(code: string, examples: unknown[]): Explanation {
  return {
    title: `Invariant ${code} fails`,
    what: (INVARIANTS[code] ?? "A rule the data must keep.") + " Checked on what the import loaded and rebuilt.",
    why: [`${examples.length ? "Examples below. " : ""}When every authoritative row equals the archive's, the failure is in the source's own data, not the import's.`],
    todo: code === "uniqueness"
      ? ["Fix it after the import: give one of the records another identifier, or merge them if they are the same thing.", ACCEPT]
      : [ACCEPT, "If it is the import's doing (an authoritative family also differs), report it."],
  };
}

export const DRY_RUN_OUTCOMES: Record<string, Explanation> = {
  divergent: {
    title: "Divergent rows",
    what: "A row with this key already exists here with other content, and it was not made by this archive's origin.",
    todo: ["For catalogue rows, choose \"keep what's here\" or \"use the archive's version\" below.",
      "For anything else, the import is blocked: an archive never overwrites local work."],
  },
  unresolved_reference: {
    title: "Unresolved references",
    what: "A row names something neither this instance nor the archive has (a type, a workspace, a record).",
    todo: ["Set \"References the archive and this instance both lack\" to leave them unresolved, or import what they name first (the base of an increment)."],
  },
};
