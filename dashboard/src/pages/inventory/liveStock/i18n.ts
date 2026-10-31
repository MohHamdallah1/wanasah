export type LiveStockCp7Copy = {
  batchDetails: string;
  openBatchDetails: string;
  loadingBatches: string;
  noBatches: string;
  sourceEvidence: string;
  sourceLoading: string;
  sourceUnavailable: string;
  sourceScopeNotice: string;
  freshnessNotice: string;
  staleBatchDetails: string;
  sourceWarehouse: string;
  movableQuantity: string;
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
  reservationReference: string;
  noKnownReservationOwners: string;
  reservationOwnersTruncated: string;
  mobileOpen: string;
};

const ar: LiveStockCp7Copy = {
  batchDetails: "تفاصيل تشغيلات الرصيد",
  openBatchDetails: "عرض تفاصيل التشغيلات",
  loadingBatches: "جاري تحميل تفاصيل التشغيلات...",
  noBatches: "لا توجد تشغيلات لها رصيد في هذا المستودع.",
  sourceEvidence: "دليل مصدر المستودع القابل للإجراء والحجوزات",
  sourceLoading: "جاري تحميل دليل المصدر...",
  sourceUnavailable: "تعذر تحميل دليل المصدر لهذا المستودع.",
  sourceScopeNotice: "هذا دليل إجراءات للمستودع المحدد فقط، وليس جرداً كاملاً لكل المواقع الفعلية. عهدة المركبات إفصاح منفصل؛ مخزون النقل الجاري والإتلاف ليس ضمن إجمالي المستودع، وعدم ظهوره هنا لا يعني أنه صفر.",
  freshnessNotice: "القائمة والملخص والتشغيلات ودليل المصدر قراءات مستقلة وليست لقطة ذرية واحدة؛ قد تتغير الكميات بينها. حدّث للتحقق.",
  staleBatchDetails: "تفاصيل التشغيلات السابقة لم تعد مؤكدة بعد التحديث. أعد المحاولة للتحقق.",
  sourceWarehouse: "المستودع",
  movableQuantity: "قابل للحركة",
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
  reservationReference: "مرجع الحجز",
  noKnownReservationOwners: "لا توجد مراجع حجوزات معروفة ضمن الدليل المعروض.",
  reservationOwnersTruncated: "القائمة مقتطعة: يوجد أصحاب حجوزات معروفون آخرون لم تعرضهم الاستجابة.",
  mobileOpen: "فتح التفاصيل",
};

const en: LiveStockCp7Copy = {
  batchDetails: "Live stock batch details",
  openBatchDetails: "View batch details",
  loadingBatches: "Loading batch details...",
  noBatches: "No batch currently has stock in this warehouse.",
  sourceEvidence: "Actionable Warehouse source and reservations",
  sourceLoading: "Loading source evidence...",
  sourceUnavailable: "Source evidence could not be loaded for this warehouse.",
  sourceScopeNotice: "This is action evidence for the selected Warehouse, not a complete physical-inventory total. Readable Vehicle custody is disclosed separately; IN_TRANSIT and SCRAP stock is outside the Warehouse total, and absence here does not mean zero.",
  freshnessNotice: "The list, summary, batches and source evidence are independent reads, not one atomic snapshot. Quantities can change between reads; refresh to verify.",
  staleBatchDetails: "Previous batch details are no longer verified after refresh. Retry to check.",
  sourceWarehouse: "Warehouse",
  movableQuantity: "Movable quantity",
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
  reservationReference: "Reservation reference",
  noKnownReservationOwners: "No known reservation references in the returned evidence.",
  reservationOwnersTruncated: "Truncated list: additional known reservation owners were not included in this response.",
  mobileOpen: "Open details",
};

export const getLiveStockCp7Copy = (language: string | undefined): LiveStockCp7Copy =>
  language?.toLowerCase().startsWith("ar") ? ar : en;
