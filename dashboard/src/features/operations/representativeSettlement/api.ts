import type { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseInventoryLocationCapabilities } from "@/hooks/useInventoryAccess";
import {
  custodyReceiveResultSchema,
  custodySnapshotSchema,
  recountSheetSchema,
  varianceReviewSchema,
  warehousePageSchema,
  type CustodyCountInput,
  type CustodySnapshot,
  type ReceivingWarehouse,
  type RecountSheet,
  type VarianceReview,
} from "./contracts";
import { executeRepresentativeSettlementCommand } from "./durableCommand";

export type SettlementAuthFetch = ReturnType<typeof useAuthFetch>;

const invalid = (code: string): never => {
  const error = new Error(code) as Error & { code: string };
  error.code = code;
  throw error;
};

const parse = <T>(result: { success: boolean; data?: T }, code: string): T =>
  result.success ? result.data as T : invalid(code);

export async function readCustody(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  signal?: AbortSignal,
): Promise<CustodySnapshot> {
  return parse(
    custodySnapshotSchema.safeParse(
      await authFetch("/admin/sessions/" + sessionId + "/inventory-custody", { signal }),
    ),
    "REPRESENTATIVE_CUSTODY_RESPONSE_INVALID",
  );
}

export async function readVariance(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  signal?: AbortSignal,
): Promise<VarianceReview> {
  return parse(
    varianceReviewSchema.safeParse(
      await authFetch("/admin/sessions/" + sessionId + "/inventory-custody/variance", { signal }),
    ),
    "REPRESENTATIVE_VARIANCE_RESPONSE_INVALID",
  );
}

export async function readRecountSheet(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  signal?: AbortSignal,
): Promise<RecountSheet> {
  return parse(
    recountSheetSchema.safeParse(
      await authFetch("/admin/sessions/" + sessionId + "/inventory-custody/variance/count-sheet", { signal }),
    ),
    "REPRESENTATIVE_RECOUNT_SHEET_INVALID",
  );
}

export async function loadReceivingWarehouses(
  authFetch: SettlementAuthFetch,
  signal?: AbortSignal,
): Promise<ReceivingWarehouse[]> {
  const warehouses: ReceivingWarehouse[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;

  do {
    const params = new URLSearchParams({ limit: "200" });
    if (cursor) params.set("cursor", cursor);
    const page = parse(
      warehousePageSchema.safeParse(
        await authFetch("/warehouse/locations?" + params.toString(), { signal }),
      ),
      "SETTLEMENT_WAREHOUSE_RESPONSE_INVALID",
    );
    warehouses.push(...page.items);
    if (page.next_cursor && seen.has(page.next_cursor)) invalid("SETTLEMENT_WAREHOUSE_CURSOR_LOOP");
    if (page.next_cursor) seen.add(page.next_cursor);
    cursor = page.next_cursor;
  } while (cursor);

  const allowed = new Set<number>();
  for (let index = 0; index < warehouses.length; index += 100) {
    const ids = warehouses.slice(index, index + 100).map((item) => item.id);
    if (!ids.length) continue;
    const raw = await authFetch("/inventory/access/locations/capabilities", {
      method: "POST",
      signal,
      body: JSON.stringify({ location_ids: ids }),
    });
    const capabilities = parseInventoryLocationCapabilities(raw, ids);
    for (const id of ids) {
      if (capabilities[id]?.includes("transfer.destination")) allowed.add(id);
    }
  }
  return warehouses.filter((warehouse) => allowed.has(warehouse.id));
}

export async function receiveCustody(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  payload: {
    destination_location_id: number;
    receiver_confirms_handoff: true;
    items: CustodyCountInput[];
    notes: string | null;
  },
) {
  return executeRepresentativeSettlementCommand({
    operation: "custody-receive",
    sessionId,
    payload,
    send: async (body) => parse(
      custodyReceiveResultSchema.safeParse(
        await authFetch("/admin/sessions/" + sessionId + "/inventory-custody/receive", {
          method: "POST",
          body: JSON.stringify(body),
        }),
      ),
      "REPRESENTATIVE_CUSTODY_RECEIVE_RESPONSE_INVALID",
    ),
  });
}

export async function authorizeRecount(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  payload: { reason: string; authorizer_username: string; authorizer_password: string },
) {
  return executeRepresentativeSettlementCommand({
    operation: "variance-recount",
    sessionId,
    payload,
    send: (body) => authFetch(
      "/admin/sessions/" + sessionId + "/inventory-custody/variance/recount",
      { method: "POST", body: JSON.stringify(body) },
    ),
  });
}

export async function submitRecount(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  payload: { items: CustodyCountInput[]; notes: string | null },
) {
  return executeRepresentativeSettlementCommand({
    operation: "variance-count",
    sessionId,
    payload,
    send: (body) => authFetch(
      "/admin/sessions/" + sessionId + "/inventory-custody/variance/count",
      { method: "POST", body: JSON.stringify(body) },
    ),
  });
}

export async function approveVariance(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  payload: { password: string; notes: string | null },
) {
  return executeRepresentativeSettlementCommand({
    operation: "variance-approve",
    sessionId,
    payload,
    send: (body) => authFetch(
      "/admin/sessions/" + sessionId + "/inventory-custody/variance/approve",
      { method: "POST", body: JSON.stringify(body) },
    ),
  });
}
