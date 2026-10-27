import type { RouteTransfer } from "@/types/dispatch";
import { absoluteQuantity, compareQuantity, parseQuantity, validateVariantQuantity } from "@/lib/quantity";
import { formatRouteLoadQuantity, parseRouteLoadUom } from "./routeLoadUom";

const statuses = new Set(["pending", "accepted", "rejected", "cancelled"]);
const invalid = () => Object.assign(new Error(), { code: "DISPATCH_TRANSFER_RESPONSE_INVALID" });

export function parseRouteTransfers(raw: unknown): RouteTransfer[] {
  if (!Array.isArray(raw)) throw invalid();
  return raw.map((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) throw invalid();
    const value = entry as Record<string, unknown>;
    if (!Number.isSafeInteger(value.transfer_id) || Number(value.transfer_id) <= 0 ||
        typeof value.product_name !== "string" || typeof value.status !== "string" ||
        !statuses.has(value.status) || (value.created_at !== null && typeof value.created_at !== "string") ||
        typeof value.batch_id !== "string" || typeof value.can_force_cancel !== "boolean") throw invalid();
    const unit = parseRouteLoadUom(value);
    const signed = parseQuantity(value.signed_base_quantity, "signed_base_quantity", { allowNegative: true });
    validateVariantQuantity(absoluteQuantity(signed), unit.quantity_scale, unit.quantity_step);
    return { ...value, ...unit, signed_base_quantity: signed } as unknown as RouteTransfer;
  });
}

export const formatTransferQuantity = (transfer: RouteTransfer): string =>
  `${compareQuantity(transfer.signed_base_quantity, "0") < 0 ? "−" : "+"}${formatRouteLoadQuantity(
    absoluteQuantity(transfer.signed_base_quantity), transfer,
  )}`;
