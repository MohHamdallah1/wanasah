export type DispatchReservationFocus = {
  version: 1;
  kind: "reservation-owner";
  routeId: number;
  transferId: number;
  openCancel: boolean;
};

export type DispatchNavigationState = {
  dispatchNavigation: DispatchNavigationIntent;
};

export type DispatchNavigationIntent = DispatchReservationFocus |
  { version: 1; kind: "route-load"; routeId: number } |
  { version: 1; kind: "shortage-owner"; shortageId: number };

export function createDispatchOwnerFocusState(
  intent: Exclude<DispatchNavigationIntent, DispatchReservationFocus>,
): DispatchNavigationState {
  return { dispatchNavigation: intent };
}

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
): DispatchNavigationIntent | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = (value as Record<string, unknown>).dispatchNavigation;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  if (row.version === 1 && row.kind === "route-load" && positiveInt(row.routeId)) {
    return { version: 1, kind: row.kind, routeId: row.routeId };
  }
  if (row.version === 1 && row.kind === "shortage-owner" && positiveInt(row.shortageId)) {
    return { version: 1, kind: row.kind, shortageId: row.shortageId };
  }
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
