import { useCallback, useEffect, useRef, useState } from "react";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import { apiErrorStatus } from "@/lib/apiErrors";
import {
  clearConfirmedShortage, prepareShortageCommand, readPendingShortage,
  shortageCommandBody, type ShortageCommandReceipt, type ShortagePendingCommand,
} from "./contract";
import type { ShortageDraftRow } from "../dispatchDrafts";

type Fetch = (path: string, options?: RequestInit) => Promise<unknown>;
type Props = {
  session: DashboardSession;
  actorScope: string | null;
  authorized: boolean;
  fetch: Fetch;
  onRestored: (pending: ShortagePendingCommand) => void;
  onCommitted: (receipt: ShortageCommandReceipt) => void;
};
export type ShortageCommandState = {
  pending: ShortagePendingCommand | null;
  busy: boolean;
  blocked: boolean;
  feedback: "unknown" | "conflict" | "denied" | "invalid" | "another-tab" | "storage" | null;
};

/** UUID replay is the only resolution of an ambiguous create, never a fresh GET. */
export function useShortageCommandCommit({
  session, actorScope, authorized, fetch, onRestored, onCommitted,
}: Props) {
  const [state, setState] = useState<ShortageCommandState>({
    pending: null, busy: false, blocked: false, feedback: null,
  });
  const flight = useRef(false);
  const onRestoredRef = useRef(onRestored);
  const onCommittedRef = useRef(onCommitted);
  onRestoredRef.current = onRestored;
  onCommittedRef.current = onCommitted;
  const scope = authorized ? actorScope : null;
  const live = useCallback(() => authorized && Boolean(scope) &&
    isDashboardSessionCurrent(session), [authorized, scope, session]);

  useEffect(() => {
    if (!live()) {
      setState({pending: null, busy: false, blocked: false, feedback: null});
      return;
    }
    try {
      const saved = readPendingShortage(scope);
      setState({pending: saved, busy: false, blocked: false,
        feedback: saved ? "unknown" : null});
      if (saved) onRestoredRef.current(saved);
    } catch {
      // Corrupt/missing durable evidence must NOT be silently overwritten.
      setState({pending: null, busy: false, blocked: true, feedback: "storage"});
    }
  }, [scope, live, session.generation, session.identity]);

  const perform = useCallback(async (
    submitted: {zone: string; shop: string; driver: string; rows: ShortageDraftRow[]} | null,
    retry: boolean,
  ): Promise<boolean> => {
    if (!live() || !scope || flight.current || state.busy || state.blocked) return false;
    if (typeof navigator === "undefined" || !navigator.locks?.request) {
      setState(s => ({...s, feedback: "storage", blocked: true}));
      return false;
    }
    flight.current = true;
    setState(s => ({...s, busy: true, feedback: null}));
    try {
      return await navigator.locks.request(
        "wanasah:shortage-command:v2:" + scope,
        {mode: "exclusive", ifAvailable: true},
        async lock => {
          if (!live()) return false;
          if (!lock) {
            setState(s => ({...s, feedback: "another-tab"}));
            return false;
          }
          let original: ShortagePendingCommand;
          try {
            const existing = readPendingShortage(scope);
            if (retry) {
              // The original UUID and payload must still be the same durable record.
              if (!existing || !state.pending ||
                  existing.command.request_id !== state.pending.command.request_id) {
                setState(s => ({...s, pending: existing, feedback: "unknown"}));
                if (existing) onRestoredRef.current(existing);
                return false;
              }
              original = existing;
            } else {
              if (existing) {
                setState(s => ({...s,pending:existing,feedback:"unknown"}));
                onRestoredRef.current(existing);
                return false; // never overwrite or regenerate unresolved intent
              }
              if (!submitted) return false;
              // Browser-generated UUID v4; persistence is verified before the POST.
              const result = prepareShortageCommand(scope,
                submitted.zone, submitted.shop, submitted.driver,
                submitted.rows, () => crypto.randomUUID());
              original = result.pending;
              if (result.existing) return false;
              setState(s => ({...s,pending:original}));
            }
          } catch {
            setState(s => ({...s,blocked:true,feedback:"storage"}));
            return false;
          }
          if (!live()) return false;
          try {
            const response = await fetch("/dispatch/shortage-commands", {
              method: "POST",
              body: JSON.stringify(shortageCommandBody(original)),
            });
            if (!live()) return false;
            // An acknowledged HTTP success with no exact immutable line
            // receipt is still UNKNOWN. A subsequent list is not evidence.
            const { parseShortageReceipt } = await import("./contract");
            const receipt = parseShortageReceipt(response, original.command);
            if (!receipt) {
              setState(s => ({...s,pending:original,feedback:"unknown"}));
              return false;
            }
            onCommittedRef.current(receipt);
            // A confirmed server receipt is the only permission to retire
            // this actor's durable command. Never clear a different UUID.
            clearConfirmedShortage(scope, original.command.request_id);
            setState({pending:null,busy:true,blocked:false,feedback:null});
            return true;
          } catch (error) {
            if (!live()) return false;
            const status = apiErrorStatus(error);
            const denied = status === 401 || status === 403;
            setState(s => ({
              ...s,
              pending: denied ? null : original,
              feedback: denied ? "denied" : status === 409 ? "conflict" : "unknown",
              blocked: denied || status === 409,
            }));
            // Do not clear stored command for any 409, 5xx, timeout, lost 201.
            return false;
          }
        },
      );
    } catch {
      if (live()) setState(s => ({...s,feedback:"storage",blocked:true}));
      return false;
    } finally {
      flight.current = false;
      if (live()) setState(s => ({...s,busy:false}));
    }
  }, [fetch,live,scope,state.pending,state.busy,state.blocked]);
  const save = useCallback((zone: string, shop: string, driver: string, rows: ShortageDraftRow[]) =>
    perform({zone,shop,driver,rows}, false), [perform]);
  const retry = useCallback(() => perform(null, true), [perform]);
  return {
    ...state, pending: authorized && live() ? state.pending : null,
    save,retry,hasUnresolved: Boolean(state.pending) || state.blocked,
  };
}
