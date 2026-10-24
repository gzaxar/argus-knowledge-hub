import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { directoryApi } from "../api/client";
import { Asset, MemberDirectoryEntry, SchemaAttribute } from "../api/types";
import { findOption } from "../lib/schemaAttributes";
import { MarkdownView } from "./MarkdownView";

function GroupValue({ value }: { value: string }) {
  const groups = useQuery({ queryKey: ["directory-groups"], queryFn: () => directoryApi.groups() });
  const group = groups.data?.find((g) => g.uid === value);
  return (
    <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-slate-700" title="Group">
      {group?.name ?? (groups.isLoading ? "…" : value)}
    </span>
  );
}

const URL_RE = /^https?:\/\//i;

function resolveReference(value: unknown, assets: Asset[] | undefined): Asset | undefined {
  if (typeof value !== "string" || !assets) return undefined;
  return assets.find((a) => a.uid === value || a.key === value || a.name === value);
}

function SingleAttributeValue({
  attribute,
  value,
  assets,
  members,
}: {
  attribute: SchemaAttribute;
  value: unknown;
  assets?: Asset[];
  members?: MemberDirectoryEntry[];
}) {
  if (value === undefined || value === null || value === "") {
    return <span className="text-slate-300">—</span>;
  }

  if (attribute.type === "reference") {
    const target = resolveReference(value, assets);
    if (target) {
      return (
        <Link
          to={`/assets/${target.uid}`}
          className="inline-flex items-center gap-1 rounded bg-indigo-50 px-2 py-0.5 text-indigo-700 hover:bg-indigo-100"
        >
          {target.name}
        </Link>
      );
    }
    if (!assets) {
      // Asset list hasn't loaded yet — don't flag as unresolved prematurely.
      return (
        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-slate-400">
          {String(value)}
        </span>
      );
    }
    return (
      <span
        title="Unresolved reference"
        className="inline-flex items-center gap-1 rounded bg-red-50 px-2 py-0.5 text-red-700"
      >
        {String(value)}
      </span>
    );
  }

  if (attribute.type === "enumeration") {
    // An answer is stored as its option's value; one named by its id ("service_degraded") is shown by its
    // value too — showing the id is showing someone the database rather than the answer.
    const option = findOption(attribute.options, value);
    return (
      <span className="inline-flex items-center rounded bg-slate-100 px-2 py-0.5 text-slate-700">
        {option?.value ?? String(value)}
      </span>
    );
  }

  if (attribute.type === "group") {
    return <GroupValue value={String(value)} />;
  }

  if (attribute.type === "user" || attribute.type === "current_user") {
    const member = members?.find((m) => m.user_id === value);
    if (member) {
      return (
        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-slate-700">
          {member.name || member.email}
        </span>
      );
    }
    if (!members) {
      return (
        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-slate-400">
          {String(value)}
        </span>
      );
    }
    return (
      <span
        title="This user is no longer a member of the workspace"
        className="inline-flex items-center gap-1 rounded bg-red-50 px-2 py-0.5 text-red-700"
      >
        {String(value)}
      </span>
    );
  }

  if (attribute.type === "text") {
    // Long free text: Markdown from the editor, or raw HTML from an import (a Jira custom field,
    // a Confluence macro) — MarkdownView renders either, sanitized.
    return <MarkdownView markdown={String(value)} className="text-left" />;
  }

  if (attribute.type === "boolean") {
    const truthy = value === true || value === "true" || value === 1;
    return (
      <span
        className={`rounded px-2 py-0.5 text-xs ${
          truthy ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500"
        }`}
      >
        {truthy ? "Yes" : "No"}
      </span>
    );
  }

  if (attribute.type === "integer" || attribute.type === "float") {
    return <span className="font-mono tabular-nums">{String(value)}</span>;
  }

  if (attribute.type === "date" || attribute.type === "datetime") {
    const d = new Date(String(value));
    if (!isNaN(d.getTime())) {
      return (
        <span>
          {attribute.type === "date" ? d.toLocaleDateString() : d.toLocaleString()}
        </span>
      );
    }
  }

  if (typeof value === "string" && URL_RE.test(value)) {
    return (
      <a
        href={value}
        target="_blank"
        rel="noreferrer"
        className="text-indigo-600 hover:underline"
      >
        {value}
      </a>
    );
  }

  return <span>{typeof value === "object" ? JSON.stringify(value) : String(value)}</span>;
}

export function AttributeValue({
  attribute,
  value,
  assets,
  members,
}: {
  attribute: SchemaAttribute;
  value: unknown;
  assets?: Asset[];
  members?: MemberDirectoryEntry[];
}) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-300">—</span>;
    return (
      <span className="inline-flex flex-wrap items-center justify-end gap-1">
        {value.map((v, i) => (
          <SingleAttributeValue key={i} attribute={attribute} value={v} assets={assets} members={members} />
        ))}
      </span>
    );
  }

  return <SingleAttributeValue attribute={attribute} value={value} assets={assets} members={members} />;
}
