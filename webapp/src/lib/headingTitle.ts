/** The draft's first heading made the document's title: a rework's text opens with the title the model wrote, and
 *  a person who changes the title before saving would otherwise get a document with two different names. The rest
 *  of the text, and a draft with no top heading, are left as they are. */
export function withTitle(markdown: string, title: string): string {
  const t = title.trim();
  if (!t) return markdown;
  return markdown.replace(/^# .*$/m, `# ${t}`);
}
