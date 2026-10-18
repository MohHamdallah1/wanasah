import type { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTransferLocations } from "@/pages/inventory/transfers/parsers";
import {
  custodyReceiveResultSchema,
  custodySnapshotSchema,
  recountSheetSchema,
  varianceReviewSchema,
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
  const params = new URLSearchParams({
    limit: "100",
    purpose: "destination",
  });
  const locations = parseTransferLocations(
    await authFetch(
      "/warehouse/unified/transfer/locations?" + params.toString(),
      { signal },
    ),
  );
  return locations
    .filter((location) => location.location_type === "WAREHOUSE")
    .map(({ id, name, code }) => ({ id, name, code }));
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
