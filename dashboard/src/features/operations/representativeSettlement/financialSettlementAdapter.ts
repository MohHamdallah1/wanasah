import type { SettlementAuthFetch } from "./api";
import { executeRepresentativeSettlementCommand } from "./durableCommand";

export interface FinancialSettlementCommand {
  actualCash: number;
  notes: string;
}

export async function submitFinancialSettlement(
  authFetch: SettlementAuthFetch,
  sessionId: number,
  command: FinancialSettlementCommand,
) {
  return executeRepresentativeSettlementCommand({
    operation: "financial-close",
    sessionId,
    payload: {
      actual_cash: command.actualCash,
      notes: command.notes,
    },
    send: (body) =>
      authFetch("/admin/sessions/" + sessionId + "/settle", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  });
}
