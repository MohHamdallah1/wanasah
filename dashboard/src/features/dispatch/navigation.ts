export type DispatchReservationFocus = {
  version: 1;
  kind: "reservation-owner";
  routeId: number;
  transferId: number;
  openCancel: boolean;
};

export type DispatchNavigationState = {
  dispatchNavigation: DispatchReservationFocus;
};

const positiveInt = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;

export function createDispatchReservationFocusState({
  routeId,
  transferId,
  openCancel = false,
}: {
  routeId: number;
  transferId: number;
  openCancel?: boolean;
}): DispatchNavigationState {
  return {
    dispatchNavigation: {
      version: 1,
      kind: "reservation-owner",
      routeId,
      transferId,
      openCancel,
    },
  };
}

export function parseDispatchNavigationState(
  value: unknown,
): DispatchReservationFocus | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = (value as Record<string, unknown>).dispatchNavigation;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  if (
    row.version !== 1 ||
    row.kind !== "reservation-owner" ||
    !positiveInt(row.routeId) ||
    !positiveInt(row.transferId) ||
    typeof row.openCancel !== "boolean"
  ) {
    return null;
  }
  return {
    version: 1,
    kind: "reservation-owner",
    routeId: row.routeId,
    transferId: row.transferId,
    openCancel: row.openCancel,
  };
}
