export type LiveStockCp7Copy = {
  batchDetails: string;
  openBatchDetails: string;
  loadingBatches: string;
  noBatches: string;
  tabBatches: string;
  tabProblems: string;
  manageBatch: string;
  advancedInfo: string;
  noSaleIssues: string;
  batchQuantity: string;
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
  restrictedQuantityHelp: string;
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
  batchDetails: "تفاصيل الصنف",
  openBatchDetails: "عرض تفاصيل التشغيلات",
  loadingBatches: "جاري تحميل تفاصيل التشغيلات...",
  noBatches: "لا توجد تشغيلات لها رصيد في هذا المستودع.",
  tabBatches: "التشغيلات",
  tabProblems: "أسباب عدم البيع",
  manageBatch: "فتح التشغيلة والصلاحية",
  advancedInfo: "تفاصيل إضافية للمخزون والحجوزات",
  noSaleIssues: "لا توجد كمية ممنوعة من البيع ضمن التشغيلات المحمّلة.",
  batchQuantity: "كمية هذه التشغيلة",
  sourceEvidence: "تفاصيل الكمية والحجوزات",
  sourceLoading: "جاري تحميل دليل المصدر...",
  sourceUnavailable: "تعذر تحميل دليل المصدر لهذا المستودع.",
  sourceScopeNotice: "يعرض كميات التشغيلة وحجوزاتها داخل المستودع المختار فقط. بضاعة المركبات منفصلة.",
  freshnessNotice: "القائمة والملخص والتشغيلات ودليل المصدر قراءات مستقلة وليست لقطة ذرية واحدة؛ قد تتغير الكميات بينها. حدّث للتحقق.",
  staleBatchDetails: "تفاصيل التشغيلات السابقة لم تعد مؤكدة بعد التحديث. أعد المحاولة للتحقق.",
  sourceWarehouse: "المستودع",
  movableQuantity: "غير محجوز",
  loadMore: "تحميل المزيد",
  continuationFailed: "تعذر تحميل بقية التشغيلات. البيانات المحملة ما زالت ظاهرة.",
  retry: "إعادة المحاولة",
  noLot: "بدون رقم تشغيلة",
  unavailableBreakdown: "لماذا هذه الكمية غير متاحة للبيع؟",
  unavailableTotal: "إجمالي غير المتاح للبيع",
  unavailableCauses: "سبب منع البيع",
  unavailableNoAffectedBatches: "لا توجد ضمن التشغيلات المحمّلة حالياً كمية تفسّر الرقم المعروض. حدّث البيانات للتحقق من القراءات المستقلة.",
  productSaleGate: "قيد البيع الحالي على مستوى المنتج",
  productGateLoading: "جاري التحقق من قيد المنتج...",
  productGateUnavailable: "تعذر التحقق من قيد المنتج حالياً؛ لا يتم افتراض حالته.",
  productGateClear: "لا يوجد قيد بيع على مستوى المنتج؛ السبب أدناه من التشغيلات أو الصلاحية أو حالة المخزون.",
  otherSaleRestriction: "إيقاف بيع المنتج أو التشغيلة",
  restrictedQuantity: "ممنوع البيع بسبب الصلاحية أو قيد البيع",
  restrictedQuantityHelp: "الكمية التي يمنع بيعها بسبب انتهاء الصلاحية أو إيقاف بيع المنتج أو التشغيلة، دون احتساب الكميات المسحوبة أو المحجوزة للحجر أو التالفة المعروضة منفصلة. وهي ضمن غير المتاح للبيع، لا تضاف إليه.",
  expiryUnavailable: "بسبب الصلاحية",
  dispositionReason: "سبب تقييد التشغيلة",
  unavailableBreakdownNote: "هذه التشغيلات فيها كمية ممنوعة من البيع. اختر التشغيلة لمعرفة السبب والتعامل معها، دون تعديل أي رصيد من هذه الشاشة.",
  lifecycleLabels: {
    DRAFT: "المنتج مسودة وغير منشور للبيع",
    ACTIVE: "نشط",
    RETIRING: "المنتج قيد الإيقاف",
    ARCHIVED: "المنتج مؤرشف",
  },
  holdLabels: {
    NONE: "لا يوجد",
    SALES_HOLD: "إيقاف بيع",
    RECALL: "سحب المنتج من البيع",
  },
  production: "الإنتاج",
  expiry: "الصلاحية",
  disposition: "حالة التشغيلة",
  dispositionLabels: {
    RELEASED: "متاحة",
    QUARANTINED: "حجر",
    BLOCKED: "محظورة",
    RECALLED: "مسحوبة من البيع",
  },
  stockStatusLabels: {
    AVAILABLE: "رصيد غير معزول",
    QUARANTINED: "حجر",
    BLOCKED: "محظور",
    RECALLED: "مسحوب من البيع",
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
  batchDetails: "Product details",
  openBatchDetails: "View batch details",
  loadingBatches: "Loading batch details...",
  noBatches: "No batch currently has stock in this warehouse.",
  tabBatches: "Batches",
  tabProblems: "Why unavailable",
  manageBatch: "Open batch and expiry",
  advancedInfo: "Additional stock and reservation details",
  noSaleIssues: "No unavailable quantity in the loaded batches.",
  batchQuantity: "Quantity in this batch",
  sourceEvidence: "Stock and reservation details",
  sourceLoading: "Loading source evidence...",
  sourceUnavailable: "Source evidence could not be loaded for this warehouse.",
  sourceScopeNotice: "Shows this batch's stock and reservations inside the selected warehouse only; vehicle stock is separate.",
  freshnessNotice: "The list, summary, batches and source evidence are independent reads, not one atomic snapshot. Quantities can change between reads; refresh to verify.",
  staleBatchDetails: "Previous batch details are no longer verified after refresh. Retry to check.",
  sourceWarehouse: "Warehouse",
  movableQuantity: "Not reserved",
  loadMore: "Load more",
  continuationFailed: "More batches could not be loaded. Loaded data is still available.",
  retry: "Retry",
  noLot: "No lot supplied",
  unavailableBreakdown: "Why is this quantity unavailable for sale?",
  unavailableTotal: "Total unavailable for sale",
  unavailableCauses: "Reason this batch cannot be sold",
  unavailableNoAffectedBatches: "None of the currently loaded batches explains the displayed amount. Refresh to re-check the independent reads.",
  productSaleGate: "Current product-level sale gate",
  productGateLoading: "Checking the current product sale gate...",
  productGateUnavailable: "The product sale gate could not be verified; no state is assumed.",
  productGateClear: "There is no product-level sale hold; the cause below comes from batch, expiry, or stock status.",
  otherSaleRestriction: "Product or batch sales restriction",
  restrictedQuantity: "Unsellable due to expiry or sales restriction",
  restrictedQuantityHelp: "Quantity barred from sale by expiry or a product/batch restriction, excluding separately shown withdrawn, quarantined, blocked, damaged and disposal-pending stock. It is part of unavailable stock, not extra.",
  expiryUnavailable: "Expiry restriction",
  dispositionReason: "Batch restriction reason",
  unavailableBreakdownNote: "These batches have quantities unavailable for sale. Open the affected batch to manage it; nothing changes from this view.",
  lifecycleLabels: {
    DRAFT: "Product is draft and unpublished for sale",
    ACTIVE: "Active",
    RETIRING: "Product is retiring",
    ARCHIVED: "Product is archived",
  },
  holdLabels: {
    NONE: "None",
    SALES_HOLD: "Sales hold",
    RECALL: "Withdrawn from sale",
  },
  production: "Production",
  expiry: "Expiry",
  disposition: "Batch status",
  dispositionLabels: {
    RELEASED: "Released",
    QUARANTINED: "Quarantined",
    BLOCKED: "Blocked",
    RECALLED: "Withdrawn from sale",
  },
  stockStatusLabels: {
    AVAILABLE: "Regular stock (not necessarily sellable)",
    QUARANTINED: "Quarantined",
    BLOCKED: "Blocked",
    RECALLED: "Withdrawn from sale",
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
