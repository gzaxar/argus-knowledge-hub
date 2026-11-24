/** What a first ion pump's key would be with `pattern`, worked out as the pattern is typed or chosen: the saved
 *  rule's example only changed after saving, so choosing a pattern showed nothing. The server's rule decides. */
export function keyExample(pattern: string, workspaceId: string, now = new Date()): string {
  const year = String(now.getFullYear());
  return pattern
    .replace(/\{WS\}/g, workspaceId.toUpperCase())
    .replace(/\{TYPE\}/g, "IP")
    .replace(/\{YYYY\}/g, year)
    .replace(/\{YY\}/g, year.slice(2))
    .replace(/\{SEQ:(\d+)\}/g, (_, n: string) => "1".padStart(Number(n), "0"))
    .replace(/\{SEQ\}/g, "1");
}
