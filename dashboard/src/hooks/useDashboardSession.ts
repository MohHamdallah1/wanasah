import { useMemo, useSyncExternalStore } from "react";
import {
  readDashboardSessionSnapshot, subscribeDashboardSession, type DashboardSession,
} from "@/lib/authStorage";

// Subscribe without retaining access/refresh credentials in React or query keys.
export function useDashboardSession(): DashboardSession | null {
  const snapshot = useSyncExternalStore(
    subscribeDashboardSession, readDashboardSessionSnapshot, () => "",
  );
  return useMemo(() => snapshot ? JSON.parse(snapshot) as DashboardSession : null, [snapshot]);
}
