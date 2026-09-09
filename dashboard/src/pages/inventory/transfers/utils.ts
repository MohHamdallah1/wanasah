import type { TransferDraftItem } from "./types";

export const totalDraftPacks = (item: TransferDraftItem): number =>
  item.cartons * item.packs_per_carton + item.loose_packs;

export const getErrorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";

export const getMutationMessage = (raw: unknown): string => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    typeof (raw as { message?: unknown }).message !== "string"
  ) {
    throw new Error("استجابة عملية الحوالة غير صالحة.");
  }

  return (raw as { message: string }).message;
};

export const formatDate = (value: string | null): string =>
  value ? new Date(value).toLocaleString("ar-EG") : "—";
