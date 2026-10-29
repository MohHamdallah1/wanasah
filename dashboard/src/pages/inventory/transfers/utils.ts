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
export const formatDate = (value: string | null): string => {
  if (!value) return "—";
  const formatted = new Intl.DateTimeFormat("en-GB", {
    numberingSystem: "latn",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
  return formatted.replace(", ", " · ");
};
export const formatTransferDateOnly = (value: string | null): string =>
  value ? new Intl.DateTimeFormat(currentLocale(), { numberingSystem: "latn" }).format(new Date(value + "T00:00:00")) : "—";
