import { parseQuantity, type Quantity } from "@/lib/quantity";
import type { BatchTerminalAction } from "./batchStockSourcesContract";

export type BatchTerminalActionResult = {
  action: BatchTerminalAction;
  movement_ids: number[];
  completed_quantity: Quantity;
  remaining_quantity: Quantity;
  origin_transfer_header_ids: number[];
};

const invalid = (): never => {
  const error = new Error("BATCH_TERMINAL_ACTION_RESPONSE_INVALID") as Error & { code: string };
  error.code = "BATCH_TERMINAL_ACTION_RESPONSE_INVALID";
  throw error;
};

const ids = (value: unknown, max: number, allowEmpty = false) => {
  if (!Array.isArray(value) || value.length > max || (!allowEmpty && value.length === 0) ||
      value.some((item) => typeof item !== "number" || !Number.isSafeInteger(item) || item <= 0)) return invalid();
  return value as number[];
};

export function parseBatchTerminalActionResult(action: BatchTerminalAction, raw: unknown): BatchTerminalActionResult {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  const expectedEvent = action === "CONFIRM_DISPOSAL"
    ? "INVENTORY_FINAL_DISPOSAL_CONFIRMED"
    : "INVENTORY_VENDOR_HANDOVER_CONFIRMED";
  if (row.event_type !== expectedEvent) return invalid();
  let completed: Quantity;
  let remaining: Quantity;
  try {
    completed = parseQuantity(action === "CONFIRM_DISPOSAL" ? row.disposed_quantity : row.handed_over_quantity, "completed_quantity");
    remaining = parseQuantity(row.remaining_quantity, "remaining_quantity", { allowZero: true });
  } catch { return invalid(); }
  return {
    action,
    movement_ids: ids(row.movement_ids, 500),
    completed_quantity: completed,
    remaining_quantity: remaining,
    origin_transfer_header_ids: ids(row.origin_transfer_header_ids, 100, true),
  };
}
