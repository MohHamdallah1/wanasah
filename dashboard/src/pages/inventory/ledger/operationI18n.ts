import type { TFunction } from "i18next";
import type { LedgerOperation } from "./operationContracts";

const ar = {
  copy1: "مرحلة حركة موثقة",
  copy2: "التفاصيل",
  copy3: "حركة موثقة",
  copy4: "أصناف",
  copy5: "تشغيلات",
  copy6: "بدون مرجع موثق",
  copy7: "فروقات الجرد المثبتة فقط",
  varianceProducts: "أصناف بفروقات مثبتة",
  copy8: "من",
  copy9: "إلى",
  copy10: "حركة موثقة",
  copy11: "بدون مرجع",
  copy12: "حركات أصلية مسجلة",
  copy13: "هذه الحركات تخص فروقات الجرد المثبتة فقط؛ الأصناف التي لم يتغير رصيدها موجودة في تاريخ الجرد المكتمل.",
  copy14: "فتح تاريخ الجرد",
  copy15: "تعذر استكمال التفاصيل؛ الحركات المحملة محفوظة.",
  copy16: "إعادة المحاولة",
  copy17: "جاري تحميل التفاصيل...",
  copy18: "لا توجد حركات مرئية.",
  copy19: "بدون تشغيلة",
  copy20: "المنفذ",
  copy21: "دليل المرجع",
  copy22: "تصحيح التوريد",
  copy23: "جاري تحميل المزيد...",
  copy24: "طريقة عرض السجل",
  copy25: "العمليات",
  copy26: "الحركات التفصيلية",
  copy27: "عملية محملة",
  columnType: "نوع العملية",
  columnReference: "المرجع",
  columnDate: "التاريخ",
  columnRoute: "المصدر / الوجهة / المرحلة",
  columnProducts: "الأصناف",
  columnMovements: "الحركات",
  columnAction: "التفاصيل",
  operationLoadFailed: "تعذّر تحميل العمليات. يمكن إعادة المحاولة دون فقدان الحركات المعتمدة.",
  badRequest: "تعذّر تنفيذ طلب السجل؛ تحقق من المرشحات والمرجع.",
  invalidScope: "بيانات الطلب غير صالحة أو المرجع غير متاح لهذا المستودع.",
  serviceUnavailable: "خدمة السجل غير متاحة مؤقتاً. أعد المحاولة.",
  requestId: "رقم تتبع الطلب",
  errorCode: "رمز السبب",
  kindTransfer: "عملية تحويل",
  kindStocktake: "عملية جرد",
  kindReceipt: "عملية توريد",
  kindMovement: "حركة مستقلة",
  locationNotShown: "موقع غير ظاهر",
} as const;
const en: Record<keyof typeof ar, string> = {
  copy1: "Recorded movement stage",
  copy2: "Details",
  copy3: "immutable movements",
  copy4: "products",
  copy5: "lots",
  copy6: "No reference",
  copy7: "Posted variances only",
  varianceProducts: "products with posted variances",
  copy8: "From",
  copy9: "To",
  copy10: "Recorded movement",
  copy11: "No reference",
  copy12: "original immutable movements",
  copy13: "These are posted stocktake variances only. Unchanged counted products belong in completed stocktake history.",
  copy14: "Open stocktake history",
  copy15: "Could not continue details; loaded movements are retained.",
  copy16: "Retry",
  copy17: "Loading details...",
  copy18: "No visible movements.",
  copy19: "No lot",
  copy20: "Actor",
  copy21: "Reference evidence",
  copy22: "Correct inbound",
  copy23: "Loading more...",
  copy24: "Ledger display mode",
  copy25: "Operations",
  copy26: "Detailed movements",
  copy27: "loaded operations",
  columnType: "Operation",
  columnReference: "Reference",
  columnDate: "Date",
  columnRoute: "Source / destination / stage",
  columnProducts: "Products",
  columnMovements: "Movements",
  columnAction: "Details",
  operationLoadFailed: "Could not load operations. Retry without losing authorized movements.",
  badRequest: "The ledger request was rejected. Check its filters and reference.",
  invalidScope: "The request is invalid or its reference is unavailable in this warehouse.",
  serviceUnavailable: "Ledger service is temporarily unavailable. Retry.",
  requestId: "Request ID",
  errorCode: "Reason code",
  kindTransfer: "Warehouse transfer",
  kindStocktake: "Stocktake",
  kindReceipt: "Supplier receipt",
  kindMovement: "Individual movement",
  locationNotShown: "Location not shown",
};
export const ledgerOperationKindLabel = (kind: LedgerOperation["group_kind"], t: TFunction, language: string) =>
  operationText(t, language, ({
    TRANSFER: "kindTransfer", STOCKTAKE: "kindStocktake",
    RECEIPT: "kindReceipt", MOVEMENT: "kindMovement",
  } as const)[kind]);

export type OperationCopyKey = keyof typeof ar;
export const operationText = (t: TFunction, language: string, key: OperationCopyKey): string =>
  String(t(`inventoryLedger.operation.${key}`, { defaultValue: language.toLowerCase().startsWith("ar") ? ar[key] : en[key] }));

/** Display only safe bounded public error fields; never leak 5xx server bodies. */
export interface LedgerOperationFailure {
  status: number;
  code: string | null;
  requestId: string | null;
  context: string | null;
}
export function parseLedgerOperationFailure(error: unknown): LedgerOperationFailure {
  const candidate = error && typeof error === "object"
    ? error as Record<string, unknown> : {};
  const status = typeof candidate.status === "number" && Number.isFinite(candidate.status)
    ? candidate.status : 0;
  const code = typeof candidate.code === "string" && /^[A-Z0-9_]{1,80}$/.test(candidate.code)
    ? candidate.code : null;
  const requestId = typeof candidate.requestId === "string" && /^[a-zA-Z0-9._:-]{1,128}$/.test(candidate.requestId)
    ? candidate.requestId : null;
  const contextData = candidate.context && typeof candidate.context === "object" &&
    !Array.isArray(candidate.context) ? candidate.context as Record<string, unknown> : {};
  const safeFields = ["field", "reason", "limit", "reference_type", "location_id"];
  const context = status >= 400 && status < 500 && status !== 401 && status !== 403
    ? safeFields.flatMap(key => {
        const value = contextData[key];
        return (typeof value === "string" && /^[\p{L}\p{N} _.-]{1,80}$/u.test(value))
          || (typeof value === "number" && Number.isSafeInteger(value))
          ? [`${key}: ${value}`] : [];
      }).join(" · ") || null
    : null;
  return { status, code, requestId, context };
}
export function operationFailureText(
  t: TFunction, language: string, failure: LedgerOperationFailure,
): string {
  if (failure.status === 400) return operationText(t, language, "badRequest");
  if (failure.status === 422) return operationText(t, language, "invalidScope");
  if (failure.status === 503 || failure.status === 408 || failure.status === 0)
    return operationText(t, language, "serviceUnavailable");
  return operationText(t, language, "operationLoadFailed");
}

/** Full canonical movement reference-type catalog from ledgerI18n backend producer labels.
 * Never use a partial UI-only list that drops historical producer types. */
export const LEDGER_OPERATION_REFERENCE_TYPES: readonly string[] = [
  "TRANSFER",
  "STOCKTAKE",
  "STOCKTAKE_ADJUSTMENT",
  "STATUS_RECLASSIFICATION",
  "FINAL_DISPOSAL",
  "SPECIAL_TRANSFER_DISPATCH",
  "SPECIAL_TRANSFER_TERMINAL_STATUS",
  "QUALITY_HANDLING_STAGE",
  "HANDSHAKE_POST",
  "HANDSHAKE_TERMINAL_STATUS",
  "REPRESENTATIVE_CUSTODY_RECEIPT",
  "VEHICLE_LOAD_DIRECT",
  "VEHICLE_UNLOAD_DIRECT",
  "VEHICLE_UNLOAD_SAFE_STATUS",
  "VISIT_SAMPLE_OUT",
  "VISIT_REWARD_OUT",
  "INBOUND_SUPPLIER",
  "INBOUND_CORRECTION",
  "AUDIT_ADJUSTMENT",
  "DISPATCH_LOAD",
  "DISPATCH_UNLOAD",
  "HANDSHAKE_RESERVE",
  "HANDSHAKE_RELEASE",
  "HANDSHAKE_COMMIT",
  "HANDSHAKE_COMMIT_PULL",
  "DRIVER_SHORTAGE",
  "DRIVER_SURPLUS",
  "VISIT_ITEM_OUT",
  "VISIT_EXCHANGE_OUT",
  "VISIT_RETURN_IN",
  "VISIT_REVERSAL",
  "TRANSFER_DISPATCH",
  "TRANSFER_RECEIPT",
  "TRANSFER_CANCELLED",
  "TRANSFER_REJECTED",
  "STATUS_CHANGE",
  "FINAL_VENDOR_HANDOVER",
];
