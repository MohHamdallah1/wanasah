import { useEffect, useRef, useState } from "react";
import { apiErrorCode, apiErrorMessage, apiErrorStatus } from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import { productDurableScope } from "@/pages/products/productDurableScope";
import { correctionRouteBlocked } from "@/pages/products/import/correctionRouteGate";
import { loadInlineCorrectionRows } from "@/pages/products/import/loadInlineCorrectionRows";
import type { ImportMappingField } from "@/pages/products/import/importFields";
import {
  MAX_INLINE_CORRECTION_BODY_BYTES,
  formatInlineValue,
  parseInlineCorrectionAck,
  type InlineCorrectionAck,
  type InlineCorrectionIntent,
  type InlineCorrectionPage,
} from "@/pages/products/import/inlineCorrectionContracts";

type AuthFetch = (path: string, options?: RequestInit) => Promise<unknown>;
type Edits = Record<string, Partial<Record<ImportMappingField, string>>>;
type Draft = {
  jobVersion: number;
  rowVersions: Record<string, number>;
  edits: Edits;
};

type Params = {
  jobId: string;
  companyId: number | null;
  driverId: number | null;
  online: boolean;
  authFetch: AuthFetch;
  onAccepted: (ack: InlineCorrectionAck) => void;
  loadFailedMessage: string;
  saveFailedMessage: string;
};

function readDraft(key: string): Draft | null {
  try {
    const text = sessionStorage.getItem(key);
    if (!text) return null;
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const value = parsed as Draft;
    if (!Number.isSafeInteger(value.jobVersion) || value.jobVersion < 1 ||
        !value.edits || typeof value.edits !== "object" ||
        !value.rowVersions || typeof value.rowVersions !== "object") return null;
    return value;
  } catch {
    return null;
  }
}

function matchesDraft(draft: Draft, page: InlineCorrectionPage): boolean {
  if (draft.jobVersion !== page.job_version) return false;
  const rowById = new Map(page.items.map((row) => [row.row_identity, row]));
  const fields = new Set(page.fields);
  for (const [identity, values] of Object.entries(draft.edits)) {
    const row = rowById.get(identity);
    if (!row || !row.editable || draft.rowVersions[identity] !== row.version ||
        !values || typeof values !== "object" || Array.isArray(values)) return false;
    for (const [field, value] of Object.entries(values)) {
      if (!fields.has(field as ImportMappingField) || typeof value !== "string") return false;
    }
  }
  return true;
}

/** Only changed source cells are stored as protected tab-local drafts. */
export function useImportInlineCorrection({
  jobId, companyId, driverId, online, authFetch, onAccepted,
  loadFailedMessage, saveFailedMessage,
}: Params) {
  const scope = companyId && driverId
    ? productDurableScope(companyId, driverId, "product-import-inline-correction", jobId)
    : null;
  const draftKey = scope ? scope + ":draft" : null;
  const [page, setPage] = useState<InlineCorrectionPage | null>(null);
  const [edits, setEdits] = useState<Edits>({});
  const [pending, setPending] = useState<DurableCommand<InlineCorrectionIntent> | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [staleDraft, setStaleDraft] = useState(false);
  const [storageWarning, setStorageWarning] = useState(false);
  const [revision, setRevision] = useState(0);
  const savingRef = useRef(false);
  const editsRef = useRef<Edits>({});
  const aliveRef = useRef(true);
  const currentJobRef = useRef(jobId);
  const currentScopeRef = useRef(scope);
  currentScopeRef.current = scope;
  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  useEffect(() => {
    currentJobRef.current = jobId;
  }, [jobId]);

  useEffect(() => {
    if (!scope || !online) {
      setLoading(false);
      return;
    }
    let disposed = false;
    const abort = new AbortController();
    setLoading(true);
    setPage(null);
    setPending(null);
    setStaleDraft(false);
    setError(null);
    void (async () => {
      // Read pending command before making any new mutation or replacing drafts.
      const savedCommand = await readDurableCommand<InlineCorrectionIntent>(scope);
      if (!disposed) setPending(savedCommand);
      const response = await loadInlineCorrectionRows(authFetch, jobId, abort.signal);
      const savedDraft = draftKey ? readDraft(draftKey) : null;
      if (disposed) return;
      setPage(response);
      if (savedDraft) {
        editsRef.current = savedDraft.edits;
        setEdits(savedDraft.edits);
        setStaleDraft(!matchesDraft(savedDraft, response));
      } else {
        editsRef.current = {};
        setEdits({});
        setStaleDraft(false);
      }
    })().catch((cause) => {
      if (!disposed) setError(apiErrorMessage(cause, loadFailedMessage));
    }).finally(() => {
      if (!disposed) setLoading(false);
    });
    return () => {
      disposed = true;
      abort.abort();
    };
  }, [scope, jobId, online, authFetch, revision, draftKey, loadFailedMessage]);

  const change = (identity: string, field: ImportMappingField, text: string) => {
    if (!page || pending || savingRef.current || staleDraft) return;
    const row = page.items.find((candidate) => candidate.row_identity === identity);
    if (!row?.editable || !page.fields.includes(field)) return;
    const next: Edits = { ...editsRef.current };
      const changed = { ...next[identity] };
      if (text === formatInlineValue(row.values[field])) delete changed[field];
      else changed[field] = text;
      if (Object.keys(changed).length) next[identity] = changed;
      else delete next[identity];
      // Persist once per user event, not as a side effect of a React state updater.
      editsRef.current = next;
      setEdits(next);
      if (draftKey) {
        try {
          if (Object.keys(next).length) {
            const rowVersions = Object.fromEntries(page.items.map((item) => [item.row_identity, item.version]));
            sessionStorage.setItem(draftKey, JSON.stringify({
              jobVersion: page.job_version, rowVersions, edits: next,
            } satisfies Draft));
          } else {
            sessionStorage.removeItem(draftKey);
          }
          setStorageWarning(false);
        } catch {
          setStorageWarning(true);
        }
      }
  };

  const discardDraft = () => {
    if (pending || savingRef.current) return;
    if (draftKey) {
      try { sessionStorage.removeItem(draftKey); } catch { setStorageWarning(true); }
    }
    editsRef.current = {};
    setEdits({});
    setStaleDraft(false);
    setRevision((current) => current + 1);
  };

  const submit = async (recover = false) => {
    if (savingRef.current || !scope || !online || currentJobRef.current !== jobId) return;
    const currentScope = () => aliveRef.current && currentScopeRef.current === scope;
    if (!recover && (!page || staleDraft || pending)) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    let command: DurableCommand<InlineCorrectionIntent> | null = null;
    try {
      if (correctionRouteBlocked(companyId, driverId, jobId, "inline")) {
        throw new Error("PRODUCT_IMPORT_CORRECTION_ROUTE_CONFLICT");
      }
      if (recover) {
        command = await readDurableCommand<InlineCorrectionIntent>(scope);
        if (!command || command.payload.jobId !== jobId) {
          throw new Error("PRODUCT_IMPORT_INLINE_PENDING_UNAVAILABLE");
        }
      } else {
        const rows = page!.items.flatMap((row) => {
          const changes = edits[row.row_identity];
          if (!changes || !Object.keys(changes).length || !row.editable) return [];
          return [{
            row_identity: row.row_identity,
            expected_version: row.version,
            values: changes,
          }];
        });
        if (!rows.length) return;
        const intent: InlineCorrectionIntent = {
          jobId,
          expected_job_version: page!.job_version,
          rows,
        };
        const encoded = new TextEncoder().encode(JSON.stringify(intent));
        if (encoded.byteLength > MAX_INLINE_CORRECTION_BODY_BYTES) {
          throw new Error("PRODUCT_IMPORT_INLINE_TOO_MANY_BYTES");
        }
        command = await getOrCreateDurableCommand(scope, intent);
      }
      if (currentScope()) setPending(command);
      const body = {
        request_id: command.requestId,
        expected_job_version: command.payload.expected_job_version,
        rows: command.payload.rows,
      };
      const ack = parseInlineCorrectionAck(
        await authFetch("/simple-products/imports/" + encodeURIComponent(jobId) + "/correction/rows", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
        jobId,
      );
      completeDurableOperation(scope, command.requestId);
      if (draftKey) {
        try { sessionStorage.removeItem(draftKey); } catch { /* no mutation data loss */ }
      }
      if (currentScope()) {
        setPending(null);
        editsRef.current = {};
        setEdits({});
        if (currentJobRef.current === jobId) onAccepted(ack);
      }
    } catch (cause) {
      // Known rejection, before the DB commit: retry may use a new stable id
      // after the user explicitly resolves the bad input or stale versions.
      const code = apiErrorCode(cause);
      if (command && (
        [413, 415, 422].includes(apiErrorStatus(cause) ?? -1) ||
        code === "PRODUCT_IMPORT_CORRECTION_STALE_JOB" ||
        code === "PRODUCT_IMPORT_CORRECTION_STALE_ROW" ||
        code === "PRODUCT_IMPORT_CORRECTION_ROW_NOT_EDITABLE" ||
        code === "PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED" ||
        code === "PRODUCT_IMPORT_CORRECTION_CONFLICT"
      )) {
        abandonDurableOperation(scope);
        if (currentScope()) {
          setPending(null);
          if (code?.includes("STALE") || code?.includes("EXPIRED") ||
              code?.includes("NOT_EDITABLE") || code === "PRODUCT_IMPORT_CORRECTION_CONFLICT") {
            setStaleDraft(true);
          }
        }
      }
      if (currentScope() && currentJobRef.current === jobId) {
        setError(apiErrorMessage(cause, saveFailedMessage));
      }
    } finally {
      savingRef.current = false;
      if (currentScope()) setSaving(false);
    }
  };

  const changedRows = Object.values(edits).filter((values) => Object.keys(values).length).length;
  return {
    page, edits, loading, saving, pending, staleDraft, storageWarning,
    changedRows, error, online, change, discardDraft,
    reload: () => setRevision((current) => current + 1),
    submit: () => void submit(false),
    retryPending: () => void submit(true),
  };
}
