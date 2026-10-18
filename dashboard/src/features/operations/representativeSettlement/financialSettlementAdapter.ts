import type { SettlementAuthFetch } from "./api";

export interface FinancialSettlementCommand {
  actualCash: number;
  notes: string;
}

/**
 * Keep the final financial transport contract isolated here.
 * The backend may add request_id/idempotency; do not invent that payload before
 * its contract is frozen.
 */
export async function submitFinancialSettlement(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  command: FinancialSettlementCommand,
) {
  return authFetch("/admin/sessions/" + sessionId + "/settle", {
    method: "PUT",
    body: JSON.stringify({
      actual_cash: command.actualCash,
      notes: command.notes,
    }),
  });
}
