/** Validated presentation tokens emitted by the native Confluence table converter. */
export type RichTableStyle = {
  backgroundColor?: string; color?: string; width?: string;
  textAlign?: "left" | "center" | "right" | "justify";
  verticalAlign?: "top" | "middle" | "bottom";
  fontWeight?: "bold"; fontStyle?: "italic"; textDecoration?: "underline"; tableLayout?: "fixed" | "auto";
};
export function richTableClass(className: string | undefined, token: string): boolean {
  return (className ?? "").split(/\s+/).includes(token);
}
export function richCellSpan(value: unknown): number | undefined {
  if (typeof value !== "number" && typeof value !== "string") return undefined;
  if (typeof value === "string" && !/^\d+$/.test(value)) return undefined;
  const number = Number(value);
  return Number.isInteger(number) && number >= 1 && number <= 1000 ? number : undefined;
}
export function confluenceRichStyle(className?: string): RichTableStyle | undefined {
  if (!richTableClass(className, "argus-confluence-rich-node")) return undefined;
  const style: RichTableStyle = {};
  for (const token of (className ?? "").split(/\s+/)) {
    const colour = token.match(/^argus-rich-(bg|fg)-([0-9a-f]{6})$/i);
    if (colour) {
      style[colour[1].toLowerCase() === "bg" ? "backgroundColor" : "color"] = `#${colour[2]}`;
      continue;
    }
    const width = token.match(/^argus-rich-w-(\d+(?:_\d{1,3})?)(px|pct)$/);
    if (width) {
      const value = Number(width[1].replace("_", "."));
      if (value > 0 && value <= (width[2] === "pct" ? 100 : 4096)) style.width = `${value}${width[2] === "pct" ? "%" : "px"}`;
      continue;
    }
    const align = token.match(/^argus-rich-align-(left|center|right|justify)$/);
    if (align) style.textAlign = align[1] as RichTableStyle["textAlign"];
    const valign = token.match(/^argus-rich-valign-(top|middle|bottom)$/);
    if (valign) style.verticalAlign = valign[1] as RichTableStyle["verticalAlign"];
    if (token === "argus-rich-bold") style.fontWeight = "bold";
    if (token === "argus-rich-italic") style.fontStyle = "italic";
    if (token === "argus-rich-underline") style.textDecoration = "underline";
    if (token === "argus-rich-fixed") style.tableLayout = "fixed";
  }
  // Explicit presentation mode: width follows the table's content. This is
  // opt-in so existing port grids and other responsive imports keep their layout.
  if (richTableClass(className, "argus-confluence-natural-table")) {
    style.width = "auto";
    style.tableLayout = "auto";
  }
  return style;
}

type RichNode = {
  type: string;
  tagName?: string;
  properties?: { className?: unknown; span?: unknown };
  children?: RichNode[];
};

function nodeClass(node: RichNode): string {
  const value = node.properties?.className;
  return Array.isArray(value) ? value.join(" ") : typeof value === "string" ? value : "";
}
function pixelWidth(node: RichNode): number | undefined {
  const width = confluenceRichStyle(nodeClass(node))?.width;
  return width?.endsWith("px") ? Number(width.slice(0, -2)) : undefined;
}
function relativeWidth(node: RichNode, percent?: number): void {
  const tokens = nodeClass(node).split(/\s+/).filter((token) => token && !/^argus-rich-w-/.test(token));
  if (percent !== undefined && percent > 0 && percent <= 100) {
    const value = Number(percent.toFixed(3));
    if (value > 0) tokens.push(`argus-rich-w-${String(value).replace(".", "_")}pct`);
  }
  node.properties = { ...node.properties, className: [...new Set(tokens)] };
}

/** Fit imported grids to their container. Each nested table has its own column
 * basis; source pixel dimensions are proportions, not minimum viewport widths.
 * Run after sanitization so this never enables source CSS or unsafe HTML. */
export function fitConfluenceRichTables() {
  return (tree: RichNode): void => {
    function visit(node: RichNode, rich = false, basis?: number, natural = false): void {
      if (node.tagName === "table") {
        const classes = nodeClass(node);
        rich = richTableClass(classes, "argus-confluence-rich-node") && richTableClass(classes, "argus-confluence-rich-table");
        basis = undefined;
        natural = rich && richTableClass(classes, "argus-confluence-natural-table");
        if (natural) {
          node.properties = { ...node.properties, className: classes.split(/\s+/).filter((token) => token !== "argus-rich-fixed") };
          relativeWidth(node);
        } else if (rich) {
          basis = pixelWidth(node);
          const columns = (node.children ?? []).filter((child) => child.tagName === "colgroup")
            .flatMap((group) => (group.children ?? []).filter((child) => child.tagName === "col"));
          // Use actual column weights: Confluence's data-table-width can differ
          // from their sum, especially in nested grids with merged cells.
          if (columns.length && columns.every((column) => pixelWidth(column) !== undefined)) {
            basis = columns.reduce((sum, column) => sum + pixelWidth(column)! * (richCellSpan(column.properties?.span) ?? 1), 0);
          }
          node.properties = { ...node.properties, className: [...classes.split(/\s+/), "argus-rich-fixed"] };
          relativeWidth(node, 100);
        }
      } else if (rich && ["col", "colgroup", "td", "th"].includes(node.tagName ?? "")) {
        const width = pixelWidth(node);
        if (natural) relativeWidth(node);
        else if (width !== undefined) relativeWidth(node, basis ? Math.min(100, width / basis * 100) : undefined);
      }
      for (const child of node.children ?? []) visit(child, rich, basis, natural);
    }
    visit(tree);
  };
}
