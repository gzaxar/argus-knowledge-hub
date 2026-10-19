import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, documentsApi, intakeApi, schemasApi, type AssistResult } from "../../api/client";
import { finalFor, GuidedEntry } from "../../components/GuidedEntry";
import { effectiveAttributes } from "../../lib/schemaAttributes";
import { AttributeInput } from "../../components/AttributeInput";
import { DocumentAssistant } from "../../components/DocumentAssistant";
import { MarkdownEditor } from "../../components/MarkdownEditor";
import { StepsEditor } from "../../components/StepsEditor";
import { AuthorityLevel, Confidentiality, DocumentStep } from "../../api/types";

export function DocumentForm() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const relateAsset = searchParams.get("relate_asset");
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const documentSchemas = (schemas.data ?? []).filter((s) => s.applies_to === "documents");

  // Fixed up front, because attaching a file needs a document to attach
  // it to: the first attachment creates the document, and this is the uid
  // it will have. The backend names its first revision <uid>-r1.
  const [documentUid] = useState(() => crypto.randomUUID());
  const [createdUid, setCreatedUid] = useState<string | null>(null);
  const [assignedCode, setAssignedCode] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [documentTypeUid, setDocumentTypeUid] = useState(searchParams.get("document_type_uid") ?? "");
  const [authorityLevel, setAuthorityLevel] = useState<AuthorityLevel>("informativo");
  const [confidentiality, setConfidentiality] = useState<Confidentiality>("interno");
  const [isGlobal, setIsGlobal] = useState(false);
  const [bodyMarkdown, setBodyMarkdown] = useState("");
  const [steps, setSteps] = useState<DocumentStep[]>([]);
  const [attributes, setAttributes] = useState<Record<string, unknown>>({});
  const [assisted, setAssisted] = useState<AssistResult | null>(null);
  const draft = { title, document_type_uid: documentTypeUid, code, body_markdown: bodyMarkdown, attributes };

  /** Values from the checklist or the assistant, by field name. */
  const apply = (values: Record<string, unknown>) => {
    for (const [field, value] of Object.entries(values)) {
      if (field === "title") setTitle(String(value ?? ""));
      else if (field === "document_type_uid") setDocumentTypeUid(String(value ?? ""));
      else if (field === "code") setCode(String(value ?? ""));
      else if (field === "summary") setBodyMarkdown((b) => (b.trim() ? b : `${String(value)}\n`));
      // The text of a Markdown file given to the assistant, chosen as the body itself.
      else if (field === "body_markdown") setBodyMarkdown(String(value ?? ""));
      else if (field.startsWith("attributes.")) {
        const k = field.slice(11);
        setAttributes((prev) => ({ ...prev, [k]: value }));
      }
    }
  };

  const schema = documentSchemas.find((s) => s.uid === documentTypeUid);
  const attrDefs = effectiveAttributes(schema, schemas.data);

  /** Create the document if it doesn't exist yet, and return its uid.
   *
   * Attaching a file is the thing that forces this: a file belongs to a
   * revision, and there is no revision until the document exists. So the
   * first attachment saves the document as a draft — the same move
   * Confluence and Jira make — rather than refusing the file or making
   * people create the document, come back, and start again.
   */
  const ensureCreated = async (): Promise<string> => {
    if (createdUid) return createdUid;
    if (!title.trim()) {
      throw new Error("Give the document a title before attaching files.");
    }
    const created = await documentsApi.create({
      uid: documentUid,
      code: code.trim() || null,
      title: title.trim(),
      document_type_uid: documentTypeUid || null,
      authority_level: authorityLevel,
      confidentiality: confidentiality,
      body_markdown: bodyMarkdown || null,
      steps,
      attributes,
    });
    setCreatedUid(documentUid);
    setAssignedCode(created!.code);
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    return documentUid;
  };

  /** A file pasted or dropped into the editor. */
  const uploadIntoBody = async (file: File) => {
    const uid = await ensureCreated();
    const saved = await documentsApi.uploadRevisionAttachment(uid, `${uid}-r1`, file);
    return {
      url: `/v1/attachments/${saved.uid}`,
      filename: saved.filename,
      isImage: (saved.mime_type ?? "").startsWith("image/"),
    };
  };

  const createMutation = useMutation({
    mutationFn: async () => {
      // Already created by an attachment: save the rest onto it rather
      // than creating a second document with the same content.
      if (createdUid) {
        await documentsApi.update(createdUid, {
          title: title.trim(),
          document_type_uid: documentTypeUid || null,
          authority_level: authorityLevel,
          confidentiality: confidentiality,
          is_global: isGlobal && confidentiality !== "riservato",
        });
        await documentsApi.updateRevision(createdUid, `${createdUid}-r1`, {
          body_markdown: bodyMarkdown,
          steps,
          attributes,
        });
        return { uid: createdUid };
      }
      return documentsApi.create({
        uid: documentUid,
        code: code.trim() || null,
        title: title.trim(),
        document_type_uid: documentTypeUid || null,
        authority_level: authorityLevel,
        confidentiality: confidentiality,
        body_markdown: bodyMarkdown || null,
        steps,
        attributes,
      });
    },
    onSuccess: async (doc) => {
      if (assisted && doc) {
        await intakeApi.outcome(assisted.run_id, doc.uid, finalFor(assisted, draft)).catch(() => undefined);
      }
      // Opened from an asset ("Write a document"): the new document applies
      // to that asset, so it appears in the asset's Knowledge tab at once.
      if (relateAsset && doc) {
        await documentsApi
          .addRelation(doc.uid, { to_type: "asset", to_uid: relateAsset, relation_type: "describes" })
          .catch(() => undefined);
        queryClient.invalidateQueries({ queryKey: ["hub-asset", relateAsset] });
      }
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      navigate(`/documents/${doc!.uid}`);
    },
  });

  return (
    <div className="max-w-7xl">
      <h1 className="text-2xl font-semibold text-slate-900">New document</h1>
      <p className="mt-1 text-sm text-slate-500">
        Describe the document or paste its text, and its title, type and keywords are suggested; the checklist
        catches duplicates and anything that must not be stored.
      </p>
      <div className="mt-2 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">

      <form
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate();
        }}
        className="mt-6 space-y-5"
      >
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Code</label>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={assignedCode ?? "Assigned automatically"}
              // Once the document exists this is its identity, so it stops
              // being editable here.
              disabled={!!createdUid}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"
            />
            <p className="mt-1 text-xs text-slate-500">
              {assignedCode
                ? `Assigned ${assignedCode}.`
                : "Leave blank and one is assigned from the type. Type your own if the document already has a number."}
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Type</label>
            <select
              value={documentTypeUid}
              onChange={(e) => {
                setDocumentTypeUid(e.target.value);
                setAttributes({});
              }}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">None</option>
              {documentSchemas.map((s) => (
                <option key={s.uid} value={s.uid}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Title</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Authority level</label>
            <select
              value={authorityLevel}
              onChange={(e) => setAuthorityLevel(e.target.value as AuthorityLevel)}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="ufficiale">Ufficiale</option>
              <option value="informativo">Informativo</option>
              <option value="bozza_interna">Bozza interna</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Confidentiality</label>
            <select
              value={confidentiality}
              onChange={(e) => setConfidentiality(e.target.value as Confidentiality)}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="pubblico">Pubblico</option>
              <option value="interno">Interno</option>
              <option value="riservato">Riservato</option>
            </select>
          </div>
        </div>

        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={isGlobal && confidentiality !== "riservato"}
            disabled={confidentiality === "riservato"}
            onChange={(e) => setIsGlobal(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            Share with every workspace
            <span className="block text-xs text-slate-500">
              {confidentiality === "riservato"
                ? "Not available for a riservato document — confidential and readable everywhere cannot both be true."
                : "For documentation that covers more than one beamline. Other workspaces can read it; editing stays here."}
            </span>
          </span>
        </label>

        <div>
          <label className="block text-sm font-medium text-slate-700">Body</label>
          <div className="mt-1">
            <MarkdownEditor
              value={bodyMarkdown}
              onChange={setBodyMarkdown}
              onUpload={uploadIntoBody}
              rows={12}
            />
            <DocumentAssistant
              title={title}
              documentTypeUid={documentTypeUid || null}
              body={bodyMarkdown}
              onDraft={setBodyMarkdown}
            />
          </div>
          {createdUid && (
            <p className="mt-1 text-xs text-slate-500">
              Saved as a draft so the files had somewhere to go — it is in the documents list
              already. Press “Save document” when you have finished the rest.
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Steps</label>
          <div className="mt-1 rounded border border-slate-200 p-3">
            <StepsEditor steps={steps} onChange={setSteps} />
          </div>
        </div>

        {schema && attrDefs.length > 0 && (
          <div>
            <label className="block text-sm font-medium text-slate-700">
              {schema.name} attributes
            </label>
            <div className="mt-2 space-y-3 rounded border border-slate-200 p-3">
              {attrDefs.map((attr) => (
                <div key={attr.id ?? attr.name}>
                  <label className="block text-xs font-medium text-slate-500">
                    {attr.name}
                    {attr.required && <span className="text-red-500"> *</span>}
                  </label>
                  <div className="mt-1">
                    <AttributeInput
                      attribute={attr}
                      appliesTo="documents"
                      value={attributes[attr.key ?? attr.name]}
                      onChange={(v) =>
                        setAttributes((prev) => ({ ...prev, [attr.key ?? attr.name]: v }))
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {createMutation.isError && (
          <p className="text-sm text-red-600">
            {createMutation.error instanceof ApiError
              ? JSON.stringify(createMutation.error.body)
              : "Failed to create document"}
          </p>
        )}

        <button
          type="submit"
          disabled={createMutation.isPending}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {createMutation.isPending
            ? "Saving…"
            : createdUid
              ? "Save document"
              : "Create document"}
        </button>
      </form>
      <aside className="xl:sticky xl:top-4 xl:self-start">
        <GuidedEntry kind="document" draft={draft} onApply={apply} onAssist={setAssisted} />
      </aside>
      </div>
    </div>
  );
}
