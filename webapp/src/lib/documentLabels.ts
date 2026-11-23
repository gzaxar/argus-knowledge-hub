/** The words a person reads for a document's stored values: "bozza_interna" and "riservato" are what the database
 *  keeps (and what Italian procedures call them), not what an English page should show. Unknown values pass as they are. */
export const AUTHORITY_LABELS: Record<string, string> = {
  ufficiale: "Official",
  informativo: "Informative",
  bozza_interna: "Internal draft",
};

export const CONFIDENTIALITY_LABELS: Record<string, string> = {
  pubblico: "Public",
  interno: "Internal",
  riservato: "Confidential",
};

export const authorityLabel = (v?: string | null) => (v ? AUTHORITY_LABELS[v] ?? v : "");
export const confidentialityLabel = (v?: string | null) => (v ? CONFIDENTIALITY_LABELS[v] ?? v : "");
