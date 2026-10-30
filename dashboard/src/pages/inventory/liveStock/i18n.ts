export type LiveStockCp7Copy = {
  batchDetails: string;
  openBatchDetails: string;
  loadingBatches: string;
  noBatches: string;
  sourceEvidence: string;
  sourceLoading: string;
  sourceUnavailable: string;
  freshnessNotice: string;
  staleBatchDetails: string;
  sourceWarehouse: string;
  loadMore: string;
  continuationFailed: string;
  retry: string;
  noLot: string;
  production: string;
  expiry: string;
  disposition: string;
  dispositionLabels: Record<"RELEASED" | "QUARANTINED" | "BLOCKED" | "RECALLED", string>;
  stockStatusLabels: Record<
    "AVAILABLE" | "QUARANTINED" | "BLOCKED" | "RECALLED" | "DAMAGED" | "DISPOSAL_PENDING",
    string
  >;
  reservationCoverage: Record<"NONE" | "COMPLETE" | "PARTIAL" | "UNRESOLVED", string>;
  reservationEvidence: string;
  unattributedReservation: string;
  reservationOwners: string;
  mobileOpen: string;
};

const ar: LiveStockCp7Copy = {
  batchDetails: "تفاصيل تشغيلات الرصيد",
  openBatchDetails: "عرض تفاصيل التشغيلات",
  loadingBatches: "جاري تحميل تفاصيل التشغيلات...",
  noBatches: "لا توجد تشغيلات لها رصيد في هذا المستودع.",
  sourceEvidence: "مصدر الرصيد والحجوزات",
  sourceLoading: "جاري تحميل دليل المصدر...",
  sourceUnavailable: "تعذر تحميل دليل المصدر لهذا المستودع.",
  freshnessNotice: "القائمة والتشغيلات ودليل المصدر قراءات مستقلة؛ قد تتغير الكميات بعد جلبها. حدّث للتحقق.",
  staleBatchDetails: "تفاصيل التشغيلات السابقة لم تعد مؤكدة بعد التحديث. أعد المحاولة للتحقق.",
  sourceWarehouse: "المستودع",
  loadMore: "تحميل المزيد",
  continuationFailed: "تعذر تحميل بقية التشغيلات. البيانات المحملة ما زالت ظاهرة.",
  retry: "إعادة المحاولة",
  noLot: "بدون رقم تشغيلة",
  production: "الإنتاج",
  expiry: "الصلاحية",
  disposition: "حالة التشغيلة",
  dispositionLabels: {
    RELEASED: "متاحة",
    QUARANTINED: "حجر",
    BLOCKED: "محظورة",
    RECALLED: "مستدعاة",
  },
  stockStatusLabels: {
    AVAILABLE: "متاح",
    QUARANTINED: "حجر",
    BLOCKED: "محظور",
    RECALLED: "مستدعى",
    DAMAGED: "تالف",
    DISPOSAL_PENDING: "بانتظار الإتلاف",
  },
  reservationCoverage: {
    NONE: "لا توجد حجوزات",
    COMPLETE: "دليل الحجز مكتمل",
    PARTIAL: "دليل الحجز جزئي",
    UNRESOLVED: "دليل الحجز غير مكتمل",
  },
  reservationEvidence: "دليل الحجز",
  unattributedReservation: "كمية محجوزة غير منسوبة",
  reservationOwners: "حجوزات معروفة",
  mobileOpen: "فتح التفاصيل",
};

const en: LiveStockCp7Copy = {
  batchDetails: "Live stock batch details",
  openBatchDetails: "View batch details",
  loadingBatches: "Loading batch details...",
  noBatches: "No batch currently has stock in this warehouse.",
  sourceEvidence: "Stock source and reservations",
  sourceLoading: "Loading source evidence...",
  sourceUnavailable: "Source evidence could not be loaded for this warehouse.",
  freshnessNotice: "The list, batches and source evidence are separate reads. Quantities can change after retrieval; refresh to verify.",
  staleBatchDetails: "Previous batch details are no longer verified after refresh. Retry to check.",
  sourceWarehouse: "Warehouse",
  loadMore: "Load more",
  continuationFailed: "More batches could not be loaded. Loaded data is still available.",
  retry: "Retry",
  noLot: "No lot supplied",
  production: "Production",
  expiry: "Expiry",
  disposition: "Batch status",
  dispositionLabels: {
    RELEASED: "Released",
    QUARANTINED: "Quarantined",
    BLOCKED: "Blocked",
    RECALLED: "Recalled",
  },
  stockStatusLabels: {
    AVAILABLE: "Available",
    QUARANTINED: "Quarantined",
    BLOCKED: "Blocked",
    RECALLED: "Recalled",
    DAMAGED: "Damaged",
    DISPOSAL_PENDING: "Disposal pending",
  },
  reservationCoverage: {
    NONE: "No reservations",
    COMPLETE: "Reservation evidence complete",
    PARTIAL: "Reservation evidence partial",
    UNRESOLVED: "Reservation evidence unresolved",
  },
  reservationEvidence: "Reservation evidence",
  unattributedReservation: "Unattributed reserved quantity",
  reservationOwners: "Known reservations",
  mobileOpen: "Open details",
};

export const getLiveStockCp7Copy = (language: string | undefined): LiveStockCp7Copy =>
  language?.toLowerCase().startsWith("ar") ? ar : en;
