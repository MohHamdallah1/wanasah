import type { Zone } from "@/types/dispatch";
import { apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";

/** Client readback evidence only. Backend remains authoritative for all writes. */
export type ZoneSaveEvidence = {
  name: string;
  editingId: string | null;
  initialIds: string[];
  responseId: string | null;
};
export function verifiedZoneSave(zones: readonly Zone[], evidence: ZoneSaveEvidence): Zone | undefined {
  return evidence.editingId
    ? zones.find(zone => zone.id === evidence.editingId && zone.name === evidence.name)
    : zones.find(zone => zone.name === evidence.name &&
      (evidence.responseId
        ? zone.id === evidence.responseId
        : !evidence.initialIds.includes(zone.id)));
}

export type ScheduleAction = "update" | "clear";
export function scheduleCommand(
  action: ScheduleAction, days: number | null, startDate: string,
): { clearSchedule: true } | { intervalDays: number; startDate: string } {
  if (action === "clear") return { clearSchedule: true };
  if (days === null || !Number.isInteger(days) || days < 1 || !startDate)
    throw new Error("INVALID_ZONE_SCHEDULE");
  return { intervalDays: days, startDate };
}

export function verifiedSchedule(
  zone: Zone | undefined, action: ScheduleAction,
  days: number | null, startDate: string,
): boolean {
  return Boolean(zone && (action === "clear"
    ? !zone.intervalDays && !zone.startDate
    : zone.intervalDays === days && zone.startDate === startDate));
}

/** A deterministic 409 is a rejected duplicate, NEVER an unknown committed save. */
export function zoneSaveFailureKind(error: unknown): "duplicate" | "uncertain" | "rejected" {
  const status = apiErrorStatus(error);
  if (status === 409) return "duplicate";
  if (isAmbiguousRequestError(error) || status === undefined) return "uncertain";
  return "rejected";
}
