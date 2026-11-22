/**
 * #1068 — immutable, actor-scoped shortage command envelope.
 *
 * This is deliberately separate from D10 presentation drafts and the grouped
 * PUT durable-command ledger. Never infer a committed POST from a GET list.
 * Company/actor are derived from the authenticated Dispatch scope, never sent
 * as caller-selected authority.
 */
import type { ShortageDraftRow } from "../dispatchDrafts";

export type ShortageCommandLine = { product_id: number; quantity_base: number };
export type ShortageCommandBody = {
  version: 2;
  request_id: string;
  shop_id: number;
  zone_id: number;
  requested_driver_id: number | null;
  lines: ShortageCommandLine[];
};
export type ShortagePendingCommand = {
  kind: "WANASAH_SHORTAGE_COMMAND_V2";
  scope: string;
  command: ShortageCommandBody;
  presentation: ShortageDraftRow[];
  created_at: string;
};
export type ShortageCommandReceipt = {
  requestId: string;
  demandIds: number[];
  lines: Array<{
    productId: number; requestedBase: number;
    fulfilledBase: number; outstandingBase: number;
  }>;
};
// D10 actor-scoped prefix is explicitly retained across logout by authStorage.
// Do not use a new, unpreserved top-level prefix for an UNKNOWN command.
const keyPrefix = "wanasah:dispatch:d10:shortage-command:v2:";
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const positive = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const id = (value: string): number => {
  if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value)))
    throw new Error("SHORTAGE_INVALID_ID");
  return Number(value);
};
const validScope = (scope: string | null): scope is string =>
  typeof scope === "string" && /^\d+:\d+:\d+$/.test(scope) &&
  scope.split(":").every(x => /^[1-9]\d*$/.test(x));
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function buildShortageIntent(
  zoneId: string, shopId: string, driverId: string, rows: readonly ShortageDraftRow[],
  requestId: string,
): ShortageCommandBody {
  if (!uuidV4.test(requestId) || rows.length < 1 || rows.length > 80) throw new Error("SHORTAGE_INVALID_INTENT");
  const lines = rows.map(row => ({
    product_id: id(row.productId), quantity_base: row.quantity,
  })).sort((a, b) => a.product_id - b.product_id);
  if (lines.some(line => !positive(line.quantity_base)) ||
      new Set(lines.map(line => line.product_id)).size !== lines.length)
    throw new Error("SHORTAGE_INVALID_LINES");
  return {
    version: 2, request_id: requestId,
    shop_id: id(shopId), zone_id: id(zoneId),
    requested_driver_id: driverId ? id(driverId) : null,
    lines,
  };
}

export function pendingShortageKey(scope: string): string {
  if (!validScope(scope)) throw new Error("SHORTAGE_ACTOR_SCOPE_UNVERIFIED");
  return keyPrefix + scope;
}
export function isShortagePending(raw: unknown, scope: string): raw is ShortagePendingCommand {
  if (!validScope(scope) || !raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const row = raw as Partial<ShortagePendingCommand>;
  if (row.kind !== "WANASAH_SHORTAGE_COMMAND_V2" || row.scope !== scope ||
      !row.command || !uuidV4.test(String(row.command.request_id)) ||
      !Array.isArray(row.presentation) || typeof row.created_at !== "string") return false;
  try {
    const expected = buildShortageIntent(String(row.command.zone_id),
      String(row.command.shop_id), row.command.requested_driver_id === null ? "" :
        String(row.command.requested_driver_id), row.presentation, row.command.request_id);
    if (!same(expected, row.command) || row.presentation.length !== expected.lines.length ||
        row.presentation.some(p => typeof p.productName !== "string" ||
          p.productName.length < 1 || p.productName.length > 300 ||
          (p.baseUomCode != null && (typeof p.baseUomCode !== "string" ||
            p.baseUomCode.length > 64)))) return false;
    return true;
  } catch { return false; }
}
export function readPendingShortage(scope: string | null): ShortagePendingCommand | null {
  if (!validScope(scope)) return null;
  try {
    const raw = localStorage.getItem(pendingShortageKey(scope));
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!isShortagePending(value, scope)) throw new Error("SHORTAGE_DURABLE_CORRUPT");
    return value;
  } catch (error) {
    // Invalid persisted data is NEVER a green light for a new UUID/send.
    throw error instanceof Error ? error : new Error("SHORTAGE_DURABLE_UNAVAILABLE");
  }
}

/** Persistent write+readback is REQUIRED before network submission. */
export function prepareShortageCommand(scope: string | null, zoneId: string,
  shopId: string, driverId: string, rows: readonly ShortageDraftRow[],
  uuidFactory: () => string,
): { pending: ShortagePendingCommand; existing: boolean } {
  if (!validScope(scope)) throw new Error("SHORTAGE_ACTOR_SCOPE_UNVERIFIED");
  const old = readPendingShortage(scope);
  if (old) return { pending: old, existing: true };
  const command = buildShortageIntent(zoneId, shopId, driverId, rows, uuidFactory());
  const pending: ShortagePendingCommand = {
    kind: "WANASAH_SHORTAGE_COMMAND_V2", scope, command,
    presentation: rows.map(r => ({
      productId: r.productId, productName: r.productName, quantity: r.quantity,
      baseUomCode: r.baseUomCode ?? null,
    })),
    created_at: new Date().toISOString(),
  };
  if (!isShortagePending(pending, scope)) throw new Error("SHORTAGE_INVALID_INTENT");
  localStorage.setItem(pendingShortageKey(scope), JSON.stringify(pending));
  if (!same(readPendingShortage(scope), pending))
    throw new Error("SHORTAGE_DURABLE_WRITE_FAILED");
  return { pending, existing: false };
}
export function clearConfirmedShortage(scope: string | null, requestId: string): void {
  if (!validScope(scope)) return;
  const pending = readPendingShortage(scope);
  if (pending && pending.command.request_id === requestId)
    localStorage.removeItem(pendingShortageKey(scope));
}

/**
 * W1 must provide authoritative immutable receipt identity, row IDs and
 * canonical base quantities. A message-only response / GET list is UNKNOWN.
 * No inferred allocation or implied visit/urgent state.
 */
export function parseShortageReceipt(raw: unknown, intent: ShortageCommandBody): ShortageCommandReceipt | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const root = raw as Record<string, unknown>;
  const response = root.receipt && typeof root.receipt === "object" &&
    !Array.isArray(root.receipt) ? root.receipt as Record<string, unknown> : root;
  // W1 #1067's actual persisted immutable receipt, not a generic message.
  // In particular, the database demand primary key is "shortage_id".
  if (response.version !== 2 || response.status !== "PENDING_REPLENISHMENT" ||
      response.request_id !== intent.request_id ||
      response.shop_id !== intent.shop_id || response.zone_id !== intent.zone_id ||
      response.requested_driver_id !== intent.requested_driver_id ||
      typeof response.request_hash !== "string" ||
      !/^[a-f0-9]{64}$/.test(response.request_hash) ||
      !Array.isArray(response.lines)) return null;
  const received = response.lines as Array<Record<string, unknown>>;
  if (received.length !== intent.lines.length) return null;
  const expected = new Map(intent.lines.map(line => [line.product_id, line.quantity_base]));
  const demandIds: number[] = [];
  const lines: ShortageCommandReceipt["lines"] = [];
  for (const value of received) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const productId = Number(value.product_id);
    const requestedBase = Number(value.requested_base);
    const fulfilledBase = Number(value.fulfilled_base);
    const outstandingBase = Number(value.outstanding_base);
    const demandId = Number(value.shortage_id);
    if (!positive(productId) || !positive(demandId) ||
        expected.get(productId) !== requestedBase || !Number.isSafeInteger(fulfilledBase) ||
        !Number.isSafeInteger(outstandingBase) || fulfilledBase < 0 || outstandingBase < 0 ||
        fulfilledBase + outstandingBase !== requestedBase ||
        demandIds.includes(demandId) || lines.some(line => line.productId === productId)) return null;
    demandIds.push(demandId);
    lines.push({productId,requestedBase,fulfilledBase,outstandingBase});
  }
  return { requestId: intent.request_id, demandIds, lines };
}
export const shortageCommandBody = (pending: ShortagePendingCommand): ShortageCommandBody =>
  pending.command;
