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
  unavailableBreakdown: string;
  unavailableTotal: string;
  unavailableCauses: string;
  unavailableNoAffectedBatches: string;
  productSaleGate: string;
  productGateLoading: string;
  productGateUnavailable: string;
  productGateClear: string;
  otherSaleRestriction: string;
  restrictedQuantity: string;
  expiryUnavailable: string;
  dispositionReason: string;
  unavailableBreakdownNote: string;
  lifecycleLabels: Record<"DRAFT" | "ACTIVE" | "RETIRING" | "ARCHIVED", string>;
  holdLabels: Record<"NONE" | "SALES_HOLD" | "RECALL", string>;
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
  unavailableBreakdown: "لماذا هذه الكمية غير متاحة للبيع؟",
  unavailableTotal: "إجمالي غير المتاح للبيع",
  unavailableCauses: "أسباب عدم الإتاحة في هذه التشغيلة",
  unavailableNoAffectedBatches: "لا توجد ضمن التشغيلات المحمّلة حالياً كمية تفسّر الرقم المعروض. حدّث البيانات للتحقق من القراءات المستقلة.",
  productSaleGate: "قيد البيع الحالي على مستوى المنتج",
  productGateLoading: "جاري التحقق من قيد المنتج...",
  productGateUnavailable: "تعذر التحقق من قيد المنتج حالياً؛ لا يتم افتراض حالته.",
  productGateClear: "لا يوجد قيد بيع على مستوى المنتج؛ السبب أدناه من التشغيلات أو الصلاحية أو حالة المخزون.",
  otherSaleRestriction: "قيد بيع آخر على مستوى المنتج أو التشغيلة",
  restrictedQuantity: "إجمالي قيود البيع",
  expiryUnavailable: "بسبب الصلاحية",
  dispositionReason: "سبب تقييد التشغيلة",
  unavailableBreakdownNote: "هذا العرض يفسّر الرقم فقط ولا يغيّر أي حالة. الكمية غير المتاحة قد تكون بسبب الصلاحية أو الحجر أو الحظر أو الاستدعاء أو التلف أو قيد بيع على المنتج/التشغيلة. الصلاحية جزء من إجمالي قيود البيع وليست كمية إضافية.",
  lifecycleLabels: {
    DRAFT: "المنتج مسودة وغير منشور للبيع",
    ACTIVE: "نشط",
    RETIRING: "المنتج قيد الإيقاف",
    ARCHIVED: "المنتج مؤرشف",
  },
  holdLabels: {
    NONE: "لا يوجد",
    SALES_HOLD: "إيقاف بيع",
    RECALL: "استدعاء منتج",
  },
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
  unavailableBreakdown: "Why is this quantity unavailable for sale?",
  unavailableTotal: "Total unavailable for sale",
  unavailableCauses: "Reasons this batch is unavailable",
  unavailableNoAffectedBatches: "None of the currently loaded batches explains the displayed amount. Refresh to re-check the independent reads.",
  productSaleGate: "Current product-level sale gate",
  productGateLoading: "Checking the current product sale gate...",
  productGateUnavailable: "The product sale gate could not be verified; no state is assumed.",
  productGateClear: "There is no product-level sale hold; the cause below comes from batch, expiry, or stock status.",
  otherSaleRestriction: "Other product or batch sale restriction",
  restrictedQuantity: "Total sale restrictions",
  expiryUnavailable: "Expiry restriction",
  dispositionReason: "Batch restriction reason",
  unavailableBreakdownNote: "This view explains the number only; it does not change any state. Unavailable stock may come from expiry, quarantine, blocking, recall, damage, or a product/batch sale restriction. Expiry is part of the restricted total, not an additional quantity.",
  lifecycleLabels: {
    DRAFT: "Product is draft and unpublished for sale",
    ACTIVE: "Active",
    RETIRING: "Product is retiring",
    ARCHIVED: "Product is archived",
  },
  holdLabels: {
    NONE: "None",
    SALES_HOLD: "Sales hold",
    RECALL: "Product recall",
  },
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
