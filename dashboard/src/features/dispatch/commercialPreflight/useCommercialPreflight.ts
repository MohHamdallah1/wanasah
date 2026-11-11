import { useCallback, useEffect, useRef, useState } from "react";
import { apiErrorStatus } from "@/lib/apiErrors";
import {
  readDashboardSessionSnapshot, subscribeDashboardSession,
} from "@/lib/authStorage";
import {
  parseCommercialPreflight, preflightSelectionValid, preflightUrl,
  type CommercialPreflight, type PreflightSelection,
} from "./contract";

type ReadinessState =
  | { key: string; status: "choose" | "loading" | "denied" | "error"; evidence: null }
  | { key: string; status: "ready" | "blocked"; evidence: CommercialPreflight };

type ReadMode = "automatic" | "event" | "timer" | "manual" | "final";
type Context = {
  key: string;
  eligible: boolean;
  session: string;
  current: () => boolean;
  fetch: PreflightReader;
  selection: PreflightSelection;
};

export type PreflightReader = (path: string, options?: RequestInit) => Promise<unknown>;

// Only an eligible, visible and online launch tab rechecks. These are advisory
// reads; every actual route POST still requires verifyBeforeLaunch's fresh GET.
const BLOCKED_RECHECK_MS = 30_000;
const ERROR_RECHECK_MS = 60_000;
const MAX_ERROR_RECHECK_MS = 120_000;
const EVENT_COALESCE_MS = 1_250;
const isForeground = () =>
  document.visibilityState !== "hidden" && navigator.onLine !== false;

export function useCommercialPreflight({
  selection, actorScope, authorized, current, fetch,
}: {
  selection: PreflightSelection;
  actorScope: string | null;
  authorized: boolean;
  current: () => boolean;
  fetch: PreflightReader;
}) {
  const eligible = Boolean(actorScope && authorized && preflightSelectionValid(selection));
  // This is a read-admission fence, never authorization. The backend checks
  // genuine Bearer/tenant/location permissions on every new request.
  const session = eligible ? readDashboardSessionSnapshot() : "";
  const key = eligible ? JSON.stringify([actorScope, session, selection.zoneId,
    selection.driverId, selection.vehicleId, selection.warehouseId]) : "";
  const [stored, setStored] = useState<ReadinessState>({
    key: "", status: "choose", evidence: null,
  });
  const storedRef = useRef<ReadinessState>(stored);
  const contextRef = useRef<Context>({ key, eligible, session, current, fetch, selection });
  contextRef.current = { key, eligible, session, current, fetch, selection };
  const sequenceRef = useRef(0);
  const flightRef = useRef<{ key: string; controller: AbortController; token: number } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const errorCountRef = useRef(0);
  const lastRequestRef = useRef(-Infinity);
  const readerRef = useRef<(mode: ReadMode) => Promise<CommercialPreflight | null>>(async () => null);

  const publish = useCallback((next: ReadinessState) => {
    storedRef.current = next;
    setStored(next);
  }, []);

  const stop = useCallback(() => {
    ++sequenceRef.current;
    flightRef.current?.controller.abort();
    flightRef.current = null;
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const schedule = useCallback((captured: Context, status: "blocked" | "error") => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (!isForeground() || !captured.eligible || !captured.current() ||
        contextRef.current.key !== captured.key ||
        captured.session !== readDashboardSessionSnapshot()) return;
    const delay = status === "blocked" ? BLOCKED_RECHECK_MS
      : Math.min(MAX_ERROR_RECHECK_MS,
        ERROR_RECHECK_MS * 2 ** Math.min(errorCountRef.current - 1, 1));
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void readerRef.current("timer");
    }, delay);
  }, []);

  const read = useCallback(async (mode: ReadMode): Promise<CommercialPreflight | null> => {
    const captured = contextRef.current;
    if (!captured.eligible || !isForeground()) return null;
    if (storedRef.current.key === captured.key && storedRef.current.status === "denied") return null;
    if (!captured.current() || captured.session !== readDashboardSessionSnapshot()) {
      stop();
      publish({ key: captured.key, status: "denied", evidence: null });
      return null;
    }
    // Burst of focus/visibility/online events is one refresh, not three.
    if (mode === "event" && Date.now() - lastRequestRef.current < EVENT_COALESCE_MS) return null;
    const flight = flightRef.current;
    if (flight && flight.key === captured.key && mode !== "final") return null;
    // Final pre-POST verification ALWAYS supersedes any background advisory read.
    if (flight) {
      ++sequenceRef.current;
      flight.controller.abort();
      flightRef.current = null;
    }
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
    const token = ++sequenceRef.current;
    const controller = new AbortController();
    flightRef.current = { key: captured.key, controller, token };
    lastRequestRef.current = Date.now();
    // Keep *blocked* reasons visible during a quiet periodic refresh; ready
    // snapshots are withdrawn until the server replies again.
    if (storedRef.current.key !== captured.key ||
        storedRef.current.status !== "blocked") {
      publish({ key: captured.key, status: "loading", evidence: null });
    }
    const admitted = () => !controller.signal.aborted &&
      sequenceRef.current === token && contextRef.current.key === captured.key &&
      contextRef.current.eligible && captured.current() &&
      captured.session === readDashboardSessionSnapshot() && isForeground();
    try {
      const raw = await captured.fetch(preflightUrl(captured.selection),
        { method: "GET", cache: "no-store", signal: controller.signal });
      if (!admitted()) return null;
      const evidence = parseCommercialPreflight(raw);
      errorCountRef.current = 0;
      publish({ key: captured.key, status: evidence.ready ? "ready" : "blocked", evidence });
      if (!evidence.ready) schedule(captured, "blocked");
      return evidence;
    } catch (error) {
      if (!admitted()) return null;
      const denied = [401, 403].includes(apiErrorStatus(error) ?? 0);
      errorCountRef.current = denied ? 0 : errorCountRef.current + 1;
      publish({ key: captured.key, status: denied ? "denied" : "error", evidence: null });
      if (!denied) schedule(captured, "error");
      return null;
    } finally {
      if (flightRef.current?.token === token) flightRef.current = null;
    }
  }, [publish, schedule, stop]);
  readerRef.current = read;

  useEffect(() => {
    // A new company, login generation, selected warehouse/vehicle/zone/rep, or
    // disabled launch tab invalidates ALL old responses before they can commit.
    stop();
    errorCountRef.current = 0;
    lastRequestRef.current = -Infinity;
    if (!eligible) {
      publish({ key, status: "choose", evidence: null });
      return;
    }
    publish({ key, status: "loading", evidence: null });
    if (isForeground()) void read("automatic");
    return stop;
  }, [key, eligible, publish, read, stop]);

  useEffect(() => {
    if (!eligible) return;
    const suspend = (offline = false) => {
      stop();
      lastRequestRef.current = -Infinity;
      if (storedRef.current.key === key &&
          (storedRef.current.status === "ready" ||
           storedRef.current.status === "loading")) {
        publish({ key, status: offline ? "error" : "loading", evidence: null });
      }
    };
    const visibility = () => {
      if (document.visibilityState === "hidden") suspend();
      else void read("event");
    };
    const focus = () => { void read("event"); };
    const online = () => { void read("event"); };
    const offline = () => suspend(true);
    const unsubscribe = subscribeDashboardSession(() => {
      if (readDashboardSessionSnapshot() !== session) {
        stop();
        publish({ key, status: "denied", evidence: null });
      }
    });
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("focus", focus);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      unsubscribe();
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("focus", focus);
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, [eligible, key, session, publish, read, stop]);

  const state: ReadinessState = eligible
    ? stored.key === key ? stored : { key, status: "loading", evidence: null }
    : { key, status: "choose", evidence: null };
  return {
    ...state,
    // A visual READY is only an advisory snapshot, never a POST authorization.
    canLaunch: eligible && state.status === "ready" && isForeground() &&
      current() && session === readDashboardSessionSnapshot(),
    verifyBeforeLaunch: () => read("final"),
    refresh: () => { void read("manual"); },
  };
}
