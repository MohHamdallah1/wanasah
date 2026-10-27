import type { CanonicalRouteTransfer, RouteTransfer, RouteTransferIdentity } from "@/types/dispatch";
import i18n, { currentLocale } from "@/i18n";
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
    const identity: RouteTransferIdentity = {
      transfer_id: Number(value.transfer_id), product_name: value.product_name,
      status: value.status as RouteTransferIdentity["status"], created_at: value.created_at as string | null,
      batch_id: value.batch_id, can_force_cancel: value.can_force_cancel,
    };
    if (value.quantity_contract === "CANONICAL_BASE_V1") {
      const unit = parseRouteLoadUom(value);
      const signed = parseQuantity(value.signed_base_quantity, "signed_base_quantity", { allowNegative: true });
      validateVariantQuantity(absoluteQuantity(signed), unit.quantity_scale, unit.quantity_step);
      return { ...identity, ...unit, quantity_contract: "CANONICAL_BASE_V1", signed_base_quantity: signed };
    }
    if (value.quantity_contract != null || !Number.isSafeInteger(value.delta_cartons) || !Number.isSafeInteger(value.delta_packs) ||
        (value.delta_cartons === 0 && value.delta_packs === 0)) throw invalid();
    // Deliberately discard any stray current UOM/base evidence on an unmarked row.
    return { ...identity, delta_cartons: Number(value.delta_cartons), delta_packs: Number(value.delta_packs) };
  });
}

export const isCanonicalRouteTransfer = (transfer: RouteTransfer): transfer is CanonicalRouteTransfer =>
  transfer.quantity_contract === "CANONICAL_BASE_V1";

export const transferIsAddition = (transfer: RouteTransfer): boolean => isCanonicalRouteTransfer(transfer)
  ? compareQuantity(transfer.signed_base_quantity, "0") > 0
  : transfer.delta_cartons > 0 || (transfer.delta_cartons === 0 && transfer.delta_packs > 0);

export function formatTransferQuantity(transfer: RouteTransfer): string {
  if (isCanonicalRouteTransfer(transfer)) {
    const unit = { ...transfer, base_uom_name: i18n.t(`uom.${transfer.base_uom_code}`, { defaultValue: transfer.base_uom_name }) };
    return `${compareQuantity(transfer.signed_base_quantity, "0") < 0 ? "−" : "+"}${formatRouteLoadQuantity(absoluteQuantity(transfer.signed_base_quantity), unit)}`;
  }
  const numbers = new Intl.NumberFormat(currentLocale(), { useGrouping: false });
  const signed = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${numbers.format(Math.abs(value))}`;
  return i18n.t("dispatchAdjustLoad.radar.legacyQuantity", { cartons: signed(transfer.delta_cartons), pieces: signed(transfer.delta_packs) });
}
