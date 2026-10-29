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
const parseServerUtcTimestamp = (value: string): Date => {
  const explicitZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
  return new Date(explicitZone ? value : `${value}Z`);
};

export const formatDate = (
  value: string | null,
  timeZone?: string,
): string => {
  if (!value) return "—";
  const date = parseServerUtcTimestamp(value);
  if (Number.isNaN(date.getTime())) return "—";
  const options: Intl.DateTimeFormatOptions = {
    numberingSystem: "latn",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    ...(timeZone ? { timeZone } : {}),
  };
  try {
    return new Intl.DateTimeFormat("en-GB", options)
      .format(date)
      .replace(", ", " · ");
  } catch {
    return new Intl.DateTimeFormat("en-GB", {
      ...options,
      timeZone: undefined,
    })
      .format(date)
      .replace(", ", " · ");
  }
};
export const formatTransferDateOnly = (value: string | null): string =>
  value ? new Intl.DateTimeFormat(currentLocale(), { numberingSystem: "latn" }).format(new Date(value + "T00:00:00")) : "—";
