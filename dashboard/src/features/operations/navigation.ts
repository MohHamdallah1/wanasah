export type SettlementOwnerIntent = { version: 1; kind: "settlement-owner"; sessionId: number };
export type OperationsNavigationState = { operationsNavigation: SettlementOwnerIntent };

export function createSettlementOwnerState(sessionId: number): OperationsNavigationState {
  return { operationsNavigation: { version: 1, kind: "settlement-owner", sessionId } };
}

export function parseOperationsNavigationState(raw: unknown): SettlementOwnerIntent | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const intent = (raw as Record<string, unknown>).operationsNavigation;
  if (!intent || typeof intent !== "object" || Array.isArray(intent)) return null;
  const row = intent as Record<string, unknown>;
  if (row.version !== 1 || row.kind !== "settlement-owner" || typeof row.sessionId !== "number" || !Number.isSafeInteger(row.sessionId) || row.sessionId <= 0) return null;
  return { version: 1, kind: row.kind, sessionId: row.sessionId };
}
