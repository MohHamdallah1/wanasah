import type { TransferDraftItem } from "./types";
import { currentLocale } from "@/i18n";
import { apiErrorMessage } from "@/lib/apiErrors";
import { transferText } from "./i18n";
import { validateVariantQuantity, type Quantity } from "../quantity";

export const totalDraftQuantity = (item: TransferDraftItem): Quantity => {
  try { return validateVariantQuantity(item.quantity, item.quantity_scale, item.quantity_step, "quantity"); }
  catch { throw Object.assign(new Error(), { code: "TRANSFER_QUANTITY_INVALID", context: { scale: item.quantity_scale, step: item.quantity_step } }); }
};
export const getErrorMessage = (error: unknown, fallback = transferText("unexpected")): string =>
  apiErrorMessage(error, fallback);
export const getMutationMessage = (raw: unknown): string => {
  if (typeof raw !== "object" || raw === null || typeof (raw as { message?: unknown }).message !== "string") {
    throw Object.assign(new Error(), { code: "TRANSFER_RESPONSE_INVALID" });
  }
  return transferText("success");
};
export const formatDate = (value: string | null): string =>
  value ? new Date(value).toLocaleString(currentLocale(), { numberingSystem: "latn" }) : "—";
export const formatTransferDateOnly = (value: string | null): string =>
  value ? new Intl.DateTimeFormat(currentLocale(), { numberingSystem: "latn" }).format(new Date(value + "T00:00:00")) : "—";
