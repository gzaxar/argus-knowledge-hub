/** File-based ELI-NP import. No network requests or AI rewriting. */
export const CONFLUENCE_SITE = "https://ifin-hh.atlassian.net";
export type ImportOptions = { sourceLink: string; sourceSpace: string; sourceVersion: string; sourceUpdated: string; sourceAuthor: string };
export type ImportedPage = {
  title: string; body: string; warnings: string[];
  metadata: Record<string, string>;
  resources: { url: string; filename: string }[];
};

// Read inline Markdown destinations with balanced parentheses and escaped labels.
// Fenced/indented code is deliberately left untouched by transformMarkdownLinks.
export function mapInlineLinks(line: string, change: (url: string, label: string) => string): string {
  let output = "", from = 0;
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "\\") { i++; continue; }
    if (line[i] === "`") {
      const run = line.slice(i).match(/^`+/)![0];
      const end = line.indexOf(run, i + run.length);
      if (end !== -1) i = end + run.length - 1;
      continue;
    }
    if (line[i] !== "[") continue;
    const labelStart = i + 1;
    let j = labelStart, depth = 1;
    for (; j < line.length; j++) {
      if (line[j] === "\\") { j++; continue; }
      if (line[j] === "[") depth++;
      if (line[j] === "]" && --depth === 0) break;
    }
    if (line[j + 1] !== "(") continue;
    const destinationStart = j + 2;
    let end = destinationStart, balance = 1;
    for (; end < line.length; end++) {
      if (line[end] === "\\") { end++; continue; }
      if (line[end] === "(") balance++;
      if (line[end] === ")" && --balance === 0) break;
    }
    if (balance !== 0) continue;
    const raw = line.slice(destinationStart, end);
    const match = raw.match(/^(<[^>]*>|\S+)([\s\S]*)$/);
    if (!match) continue;
    const angle = match[1].startsWith("<");
    const url = angle ? match[1].slice(1, -1) : match[1];
    const replacement = change(url, line.slice(labelStart, j));
    output += line.slice(from, destinationStart) + (angle ? `<${replacement}>` : replacement) + match[2];
    from = end; i = end;
  }
  return output + line.slice(from);
}

export function transformMarkdownLinks(markdown: string, change: (url: string, label: string) => string): string {
  let fence: { char: string; count: number } | null = null;
  return markdown.split("\n").map((line) => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (marker) {
      if (!fence) fence = { char: marker[1][0], count: marker[1].length };
      else if (marker[1][0] === fence.char && marker[1].length >= fence.count && /^\s*$/.test(line.slice(marker[0].length))) fence = null;
      return line;
    }
    return fence || /^( {4}|\t)/.test(line) ? line : mapInlineLinks(line, change);
  }).join("\n");
}

const cellText = (value: string) => value.replace(/\\([_\[\]*])/g, "$1").replace(/\*\*/g, "").trim();
const tableValue = (value: string) => value.replace(/\|/g, "\\|").replace(/[\r\n]/g, " ");
export function resourceName(url: string): string {
  try { return decodeURIComponent(new URL(url, CONFLUENCE_SITE).pathname.split("/").pop() ?? "").replace(/\+/g, " "); }
  catch { return ""; }
}

export function convertConfluenceMarkdown(input: string, options: ImportOptions): ImportedPage {
  const warnings: string[] = [];
  if (options.sourceLink) {
    const source = new URL(options.sourceLink);
    if (source.protocol !== "https:" || source.origin !== CONFLUENCE_SITE || !source.pathname.startsWith("/wiki/")) {
      throw new Error(`Use the original page URL under ${CONFLUENCE_SITE}/wiki/.`);
    }
  } else warnings.push("Original page URL is missing. Add it for source tracking.");
  const original = input.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const resources: ImportedPage["resources"] = [];
  const metadata: Record<string, string> = {
    profile: "eli-np-confluence", facility: "ELI-NP", source: "Confluence",
    source_link: options.sourceLink, source_space: options.sourceSpace,
    source_version: options.sourceVersion, source_updated: options.sourceUpdated,
    source_author: options.sourceAuthor,
    source_id: options.sourceLink.match(/\/pages\/(\d+)(?:\/|$)/)?.[1] ?? "",
  };
  const seen = new Set<string>();
  const linked = transformMarkdownLinks(original, (url) => {
    if (url.startsWith("/wiki/")) return CONFLUENCE_SITE + url;
    return url;
  });
  const lines = linked.split("\n"), out: string[] = [];
  let fence: string | null = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (marker) { if (!fence) fence = marker[1]; else if (marker[1][0] === fence[0] && marker[1].length >= fence.length && /^\s*$/.test(line.slice(marker[0].length))) fence = null; out.push(line); continue; }
    if (fence || /^( {4}|\t)/.test(line)) { out.push(line); continue; }
    // Only replace the known exported attachment-management table.
    if (/^\|\s*\|\s*File\s*\|\s*Modified\s*\|\s*$/i.test(line) && /^\|[\s:|-]+\|$/.test(lines[i + 1] ?? "")) {
      let end = i + 2;
      const rows: string[] = [];
      while ((lines[end] ?? "").startsWith("|")) { rows.push(lines[end]); end++; }
      const found: ImportedPage["resources"] = [];
      for (const row of rows) {
        mapInlineLinks(row, (url, label) => {
          if (/\/wiki\/download\/attachments\//.test(url) && !["View", "Properties", "Delete"].includes(label)) {
            const filename = cellText(label), key = resourceName(url);
            if (!seen.has(key)) { seen.add(key); found.push({ url, filename }); resources.push({ url, filename }); }
          }
          return url;
        });
      }
      if (found.length && rows.every((row) => /\[Properties\]|\[Delete\]|Edit Labels/.test(row))) {
        out.push("| Manual | File |", "| --- | --- |", ...found.map((r) => `| ${tableValue(r.filename)} | [Open PDF](${r.url}) |`));
        warnings.push("Converted the Confluence attachment table to resource links. Attachment modification history remains in the original export.");
        i = end - 1; continue;
      }
    }
    const owner = line.match(/^\|\s*\*\*Document owner\*\*\s*\|\s*(.*?)\s*\|\s*$/i);
    const status = line.match(/^\|\s*\*\*Document status\*\*\s*\|\s*(.*?)\s*\|\s*$/i);
    if (owner) metadata.source_owner = owner[1].replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
    if (status) metadata.source_status = cellText(status[1]);
    if (/^!\[\]\(https:\/\/ifin-hh\.atlassian\.net\/wiki\/images\/icons\/grey_arrow_down\.png\)\s*$/.test(line)) continue;
    if (line.trim() === "Manuals" && /^## Resources\s*$/m.test(original)) { out.push("### Manuals"); continue; }
    if (/^\[Download All\]\(https:\/\/ifin-hh\.atlassian\.net\/wiki\/download\/all_attachments\?pageId=\d+\)\s*$/.test(line)) continue;
    out.push(line);
  }
  if (resources.length) warnings.push(`${resources.length} resource references found. Select the corresponding PDFs/images to store copies in ARGUS; unmatched links continue to require Confluence access.`);
  if (/^\s*\[[^\]]+\]:|<img\b|<a\b/im.test(original)) warnings.push("Reference-style links or HTML detected. Check their destinations manually; only inline Markdown links are converted.");
  const titleMatch = original.match(/^#\s+(.+)$/m);
  const title = titleMatch ? cellText(titleMatch[1]) : "";
  const sourceRows = [
    ["Facility", "ELI-NP"], ["Source", "Confluence"], ["Source space", options.sourceSpace],
    ["Original page", options.sourceLink ? `[Open Confluence page](${options.sourceLink})` : "Not supplied"],
    ["Version at source", options.sourceVersion || "Not supplied"],
    ["Updated at source", options.sourceUpdated || "Not supplied"], ["Author at source", options.sourceAuthor || "Not supplied"],
  ];
  const body = out.join("\n").trimEnd() + "\n\n## Import source\n\n| Field | Value |\n| --- | --- |\n" +
    sourceRows.map(([k, v]) => `| ${k} | ${tableValue(v)} |`).join("\n") + "\n";
  return { title, body, resources, warnings, metadata };
}

/** Pure replacement: leaves external URLs untouched unless an exact resource or unique selected filename matches. */
export function replaceResourceLinks(body: string, uploaded: Map<string, string>): string {
  return transformMarkdownLinks(body, (url) => {
    if (url.startsWith("#") || url.startsWith("/v1/attachments/")) return url;
    let parsed: URL;
    try { parsed = new URL(url, CONFLUENCE_SITE); } catch { return url; }
    const local = !/^[a-z][a-z\d+.-]*:/i.test(url) && !url.startsWith("//");
    const confluenceAttachment = parsed.origin === CONFLUENCE_SITE && parsed.pathname.startsWith("/wiki/download/attachments/");
    if (!local && !confluenceAttachment) return url;
    return uploaded.get(resourceName(url)) ?? url;
  });
}
