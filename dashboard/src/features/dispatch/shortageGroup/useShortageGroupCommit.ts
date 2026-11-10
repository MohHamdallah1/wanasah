import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { apiErrorMessage, apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import {
  completeDurableOperation, getOrCreateDurableCommand, readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import type { Shortage } from "@/types/dispatch";
import {
  buildGroupIntent, groupMutationBody, groupText, isGroupIntent,
  parseGroupResponse, shortageGroupScope, groupReadbackVerdict,
  saveGroupHttpReference, readGroupHttpReference, clearGroupHttpReference,
  type GroupDraftLine, type GroupIntent, type GroupLine,
} from "./contract";

type AuthFetch = (path: string, options?: RequestInit) => Promise<unknown>;
type Args = {
  session: DashboardSession;
  authorized: boolean;
  language: string;
  fetch: AuthFetch;
  onVerified: (rows: Shortage[], command: GroupIntent) => void;
  onRefreshed: (rows: Shortage[]) => void;
  onReconciled: (rows: Shortage[]) => void;
  onRestored: (command: GroupIntent) => void;
};

const readSelected = (raw: unknown, ids: number[]): boolean => {
  if (!Array.isArray(raw) || raw.some(x => !x || typeof x !== "object")) return false;
  const selected = ids.map(id => raw.find(x => Number(x.id) === id)) as Shortage[];
  if (selected.some(x => !x || x.status !== "pending")) return false;
  // A group is one original Shop, Zone and Driver.
  return new Set(selected.map(x => `${x.shopId}:${x.zoneId}:${x.driverId || ""}`)).size === 1;
};

/** Client-only orchestration. The server's atomic idempotency and authorization
 * are the business truth; a local UUID/GET-only match cannot prove success.
 */
export function useShortageGroupCommit({
  session, authorized, language, fetch, onVerified, onRefreshed, onReconciled, onRestored,
}: Args) {
  const [pending, setPending] = useState<DurableCommand<GroupIntent> | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [blocked, setBlocked] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [httpReference, setHttpReference] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const onVerifiedRef = useRef(onVerified);
  const onRefreshedRef = useRef(onRefreshed);
  const onReconciledRef = useRef(onReconciled);
  const onRestoredRef = useRef(onRestored);
  onVerifiedRef.current = onVerified;
  onRefreshedRef.current = onRefreshed;
  onReconciledRef.current = onReconciled;
  onRestoredRef.current = onRestored;

  const live = useCallback(() => mounted.current && isDashboardSessionCurrent(session), [session]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setPending(null);
    setFeedback(null);
    setHttpReference(null);
    setBlocked(false);
    setRestoring(true);
    if (!authorized) {
      setBlocked(true);
      setRestoring(false);
      return;
    }
    const scope = shortageGroupScope();
    if (!scope) {
      setBlocked(true);
      setRestoring(false);
      return;
    }
    void readDurableCommand<GroupIntent>(scope)
      .then(record => {
        if (!active || !live() || !record) return;
        if (!isGroupIntent(record.payload)) {
          setBlocked(true);
          return;
        }
        setPending(record);
        setHttpReference(readGroupHttpReference(scope, record.requestId));
        setFeedback(groupText(language, "pending"));
        onRestoredRef.current(record.payload);
      })
      .catch(() => {
        if (active && live()) setBlocked(true);
      })
      .finally(() => {
        if (active && live()) setRestoring(false);
      });
    return () => { active = false; };
    // Only a genuine login/tenant generation changes restored authority.
  }, [authorized, session.generation, session.identity, live, language]);

  const perform = useCallback(async (
    intent: GroupIntent | null, retry: boolean,
  ): Promise<boolean> => {
    if (inFlight.current || busy || restoring || blocked || !authorized || !live()) return false;
    const scope = shortageGroupScope();
    if (!scope) {
      setBlocked(true);
      return false;
    }
    if (typeof navigator === "undefined" || !navigator.locks?.request) {
      setFeedback(groupText(language, "noLock"));
      return false;
    }

    inFlight.current = true;
    setBusy(true);
    let sent = false;
    let preflightStarted = false;
    let command: DurableCommand<GroupIntent> | null = null;
    try {
      const result = await navigator.locks.request(
        `${scope}:exclusive-shortage-group-write`, { mode: "exclusive", ifAvailable: true },
        async lock => {
          if (!lock || !live()) {
            if (live()) setFeedback(groupText(language, "otherTab"));
            return false;
          }
          const existing = await readDurableCommand<GroupIntent>(scope);
          if (!live()) return false;
          if (!existing && retry && pending) {
            // A different tab may have finished this command and cleared
            // durable storage. Refresh through real authorized GET before
            // releasing this tab's stale lock; do NOT infer success here.
            try {
              const snapshot = await fetch("/dispatch/shortages", { cache: "no-store" });
              if (!live()) return false;
              if (!Array.isArray(snapshot) || snapshot.some(row =>
                !row || typeof row !== "object")) {
                setFeedback(groupText(language, "readback"));
                return false;
              }
              onRefreshedRef.current(snapshot as Shortage[]);
              setPending(null);
              setHttpReference(null);
              setFeedback(groupText(language, "otherTabResolved"));
            } catch (error) {
              if (live()) {
                const denied = [401, 403].includes(apiErrorStatus(error) ?? 0);
                const ref = apiErrorRequestId(error);
                if (ref && pending) {
                  saveGroupHttpReference(scope, pending.requestId, ref);
                  setHttpReference(readGroupHttpReference(scope, pending.requestId));
                } else {
                  // Do not mislabel the previous PUT's reference as the
                  // current failed GET request's correlation identifier.
                  clearGroupHttpReference(scope);
                  setHttpReference(null);
                }
                setFeedback(apiErrorMessage(error,
                  groupText(language, denied ? "denied" : "readback")));
                if (denied) setBlocked(true);
              }
            }
            return false; // no PUT, no success toast, no new key
          }
          if (existing) {
            if (!isGroupIntent(existing.payload)) {
              setBlocked(true);
              return false;
            }
            if (retry && (!pending || existing.requestId !== pending.requestId)) {
              // This tab's Retry is for A, while another tab installed B.
              // Web Locks serialize mutations, but do NOT identify intent.
              setPending(existing);
              setHttpReference(readGroupHttpReference(scope, existing.requestId));
              onRestoredRef.current(existing.payload);
              setFeedback(groupText(language, "changedAttempt"));
              return false; // zero PUT for a different original request
            }
            setPending(existing);
            setHttpReference(readGroupHttpReference(scope, existing.requestId));
            if (!retry) {
              setFeedback(groupText(language, "different"));
              onRestoredRef.current(existing.payload);
              return false;
            }
            command = existing; // only the original immutable request and UUID
          } else {
            if (retry || !intent || !isGroupIntent(intent)) {
              setFeedback(groupText(language, "stale"));
              return false;
            }
            // A failed preflight proves that no PUT was sent. This cannot
            // consume a command UUID or install an uncertain operation.
            preflightStarted = true;
            const snapshot = await fetch("/dispatch/shortages", { cache: "no-store" });
            preflightStarted = false;
            if (!live()) return false;
            if (!readSelected(snapshot, intent.shortageIds)) {
              setFeedback(groupText(language, "stale"));
              return false;
            }
            command = await getOrCreateDurableCommand(scope, intent);
            if (!live()) return false;
            setPending(command);
            setHttpReference(null);
          }
          if (!command) return false;
          const original = command as DurableCommand<GroupIntent>;
          const body = groupMutationBody(original.requestId, original.payload);
          sent = true;
          let raw: unknown;
          try {
            raw = await fetch("/dispatch/shortages/group", {
              method: "PUT", body: JSON.stringify(body),
            });
          } catch (error) {
            if (live()) {
              const status = apiErrorStatus(error);
              const ref = apiErrorRequestId(error);
              if (ref) {
                saveGroupHttpReference(scope, original.requestId, ref);
                setHttpReference(readGroupHttpReference(scope, original.requestId));
              }
              const fallback = groupText(language,
                status === 401 || status === 403 ? "denied"
                  : status === 409 ? "conflict"
                    : status === 400 || status === 404 || status === 422 ? "stale" : "unknown");
              // Preserves canonical code, localized context and safe request
              // reference while redacting unexpected 5xx diagnostics.
              setFeedback(apiErrorMessage(error, fallback));
              if (status === 401 || status === 403) {
                setBlocked(true); // revoked grant requires fresh login
              }
              // 400/404/422/409 NEVER erase an ambiguous old command by
              // status alone: router/validation error is not idempotency proof.
            }
            return false;
          }
          if (!live()) return false;
          const receipt = parseGroupResponse(raw, original.requestId);
          if (!receipt) {
            setFeedback(groupText(language, "unknown"));
            return false;
          }
          // Even a server 200 needs a fresh authorized readback to finish UX.
          try {
            const rows = await fetch("/dispatch/shortages", { cache: "no-store" });
            if (!live()) return false;
            const readback = groupReadbackVerdict(rows, original.payload, receipt);
            if (!readback) {
              setFeedback(groupText(language, "readback"));
              return false;
            }
            if (readback === "subsequently-changed") {
              // Canonical exact-key PUT 200 already proves the historical
              // committed transaction. The fresh authorized list confirms
              // current state, not an immutable snapshot: later assignments,
              // fulfillment and further edits may legitimately differ.
              completeDurableOperation(scope, original.requestId);
              clearGroupHttpReference(scope);
              setPending(null);
              setHttpReference(null);
              setFeedback(groupText(language, "historicalCommit"));
              onReconciledRef.current(rows as Shortage[]);
              toast.info(groupText(language, "historicalCommit"));
              return true;
            }
            completeDurableOperation(scope, original.requestId);
            clearGroupHttpReference(scope);
            setPending(null);
            setHttpReference(null);
            setFeedback(null);
            // groupReadbackVerdict already validated every authorized row
            // before returning "exact"; TypeScript cannot infer that through
            // a multi-valued verdict.
            onVerifiedRef.current(rows as Shortage[], original.payload);
            toast.success(groupText(language,
              original.payload.action === "delete" ? "successDelete" : "successEdit"));
            return true;
          } catch (error) {
            if (live()) {
              const denied = [401, 403].includes(apiErrorStatus(error) ?? 0);
              const ref = apiErrorRequestId(error);
              if (ref) {
                saveGroupHttpReference(scope, original.requestId, ref);
                setHttpReference(readGroupHttpReference(scope, original.requestId));
              }
              setFeedback(apiErrorMessage(error,
                groupText(language, denied ? "denied" : "readback")));
              if (denied) setBlocked(true); // GET may lose its read grant
            }
            return false;
          }
        },
      );
      return result;
    } catch (error) {
      // Local storage/canonical lock failures never turn an uncertain
      // mutation into success and never make a new UUID for the same intent.
      if (live()) {
        const denied = [401, 403].includes(apiErrorStatus(error) ?? 0);
        setFeedback(groupText(language, denied ? "denied" : "unknown"));
        // A network failure during the authorized preflight is definitely
        // UNSENT and must permit an ordinary fresh attempt after reconnection.
        // Durable storage/lock failures and revoked GET authority fail closed.
        if (!sent && (!preflightStarted || denied)) setBlocked(true);
      }
      return false;
    } finally {
      inFlight.current = false;
      if (live()) setBusy(false);
    }
  }, [authorized, blocked, busy, fetch, language, live, pending, restoring]);

  const save = useCallback(async (
    shortageIds: string[], items: GroupLine[], draft: GroupDraftLine[] = [],
  ): Promise<boolean> => {
    try {
      const intent = buildGroupIntent(shortageIds, items, draft);
      return await perform(intent, false);
    } catch {
      if (live()) setFeedback(groupText(language, "stale"));
      return false;
    }
  }, [perform, live, language]);

  const retry = useCallback(() => perform(null, true), [perform]);

  return {
    save, retry, pending: authorized ? pending : null,
    restoring, busy, blocked, feedback, httpReference,
    /** Never hide an unresolved command merely because its selected IDs
     * disappeared after a lost successful PUT.
     */
    hasUnresolved: Boolean(pending), isBusy: busy || restoring,
  };
}
