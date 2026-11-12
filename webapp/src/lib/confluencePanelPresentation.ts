/** Only our fixed marker and validated hex colours become React styles. */
export function confluencePanelStyle(className?: string): { backgroundColor?: string; borderColor?: string; borderStyle?: "solid"; borderWidth?: number } | undefined {
  if (!/(?:^|\s)argus-confluence-panel(?:\s|$)/.test(className ?? "")) return undefined;
  const background = className?.match(/(?:^|\s)argus-confluence-panel-bg-([\da-f]{6})(?=\s|$)/i)?.[1];
  const border = className?.match(/(?:^|\s)argus-confluence-panel-border-([\da-f]{6})(?=\s|$)/i)?.[1];
  return {
    ...(background ? { backgroundColor: `#${background}` } : {}),
    ...(border ? { borderColor: `#${border}`, borderStyle: "solid" as const, borderWidth: 1 } : {}),
  };
}
