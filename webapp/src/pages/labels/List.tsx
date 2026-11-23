import { ask } from "../../lib/dialogs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { assetSubresourcesApi, labelsApi } from "../../api/client";
import { LABEL_TYPES } from "../../api/types";
import { LabelScanner } from "../../components/LabelScanner";

export function LabelList() {
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanMiss, setScanMiss] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["labels", search, type],
    queryFn: () => labelsApi.search({ search: search || undefined, type: type || undefined }),
  });

  const deleteMutation = useMutation({
    mutationFn: ({ assetUid, labelUid }: { assetUid: string; labelUid: string }) =>
      assetSubresourcesApi.deleteLabel(assetUid, labelUid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["labels"] }),
  });

  /** Scanning here is a lookup, not data entry: point the camera at a tag and
   * land on the object it identifies. An exact value match wins; a code that
   * matches nothing leaves the value in the search box rather than silently
   * doing nothing. */
  const resolveScan = async (value: string) => {
    setScanning(false);
    const matches = await labelsApi.search({ search: value });
    const exact = matches.find((m) => m.value === value);
    if (exact) {
      navigate(`/assets/${exact.asset_uid}`);
      return;
    }
    setSearch(value);
    setScanMiss(value);
  };

  return (
    <div>
      {scanning && (
        <LabelScanner
          title="Scan to find an object"
          onClose={() => setScanning(false)}
          onScan={resolveScan}
        />
      )}
      <h1 className="text-2xl font-semibold text-slate-900">Labels</h1>
      <p className="mt-1 text-sm text-slate-500">
        QR codes, barcodes, serial numbers, and RFID tags attached to assets.
      </p>

      <div className="mt-4 flex gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by value…"
          className="w-64 rounded border border-slate-300 px-3 py-1.5 text-sm"
        />
        <select
          aria-label="Label type"
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm"
        >
          <option value="">All types</option>
          {LABEL_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => {
            setScanMiss(null);
            setScanning(true);
          }}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          Scan a code
        </button>
      </div>

      {scanMiss && (
        <p className="mt-3 text-sm text-amber-700">
          Nothing is labelled <span className="font-mono">{scanMiss}</span> in this workspace — the
          search below is set to that value, so you can see what's close.
        </p>
      )}

      {isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && (
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Value</th>
                <th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Issuer</th>
                <th className="px-4 py-2">Verified</th>
                <th className="px-4 py-2">Asset</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((l) => (
                <tr key={l.uid} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-mono text-slate-900">{l.value}</td>
                  <td className="px-4 py-2 text-slate-500">{l.type}</td>
                  <td className="px-4 py-2 text-slate-500">{l.issuer}</td>
                  <td className="px-4 py-2 text-slate-500">{l.verified ? "Yes" : "No"}</td>
                  <td className="px-4 py-2">
                    <Link to={`/assets/${l.asset_uid}`} className="text-indigo-600 hover:underline">
                      {l.asset_name} ({l.asset_key})
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={async () => {
                        if (await ask(`Remove label "${l.value}"?`)) {
                          deleteMutation.mutate({ assetUid: l.asset_uid, labelUid: l.uid });
                        }
                      }}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                    No labels found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
