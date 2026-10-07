export const productQualityInline = {
  ar: {
    pending: "نتيجة العملية غير محسومة بعد؛ حدّث البيانات قبل إعادة المحاولة.",
    errors: {
      resolve: "تعذر تنفيذ معالجة المنتج بالكامل.",
      load: "تعذر تحميل الكميات المتأثرة.",
    },
    success: {
      DISPOSE: "تم إتلاف كل الكميات الحالية للمنتج وخصمها من مخزون الشركة.",
      RETURN_TO_VENDOR: "تم تسجيل تسليم كل الكميات الحالية للجهة المستلمة وخصمها من مخزون الشركة.",
    },
    title: "معالجة الكميات المتأثرة",
    noStock: "لا توجد كميات حالية لهذا المنتج ضمن المواقع المسموح لك برؤيتها.",
    affectedStock: "الكميات الحالية المشمولة بالقرار",
    total: "الإجمالي: {{quantity}}{{secondary}}",
    actions: {
      disposeAll: "إتلاف المنتج بالكامل",
      returnAll: "إرجاع المنتج بالكامل للمورد / المصنع",
    },
    confirm: {
      disposeTitle: "تأكيد إتلاف المنتج بالكامل",
      returnTitle: "تأكيد إرجاع المنتج بالكامل",
      scope: "سيُطبق القرار على كل الكمية الحالية في {{count}} موقع/مستودع · {{quantity}}{{secondary}}.",
      disposeButton: "تأكيد إتلاف جميع الكميات",
      returnButton: "تأكيد تسليم جميع الكميات",
    },
    fields: {
      reason: "السبب",
      method: "طريقة الإتلاف (اختياري)",
      evidence: "مرجع الدليل (اختياري)",
      recipientName: "اسم الجهة المستلمة / المورد / المصنع",
      handoverReference: "مرجع التسليم",
    },
  },
  en: {
    pending: "The operation outcome is still uncertain. Refresh before retrying.",
    errors: {
      resolve: "Could not complete whole-product quality handling.",
      load: "Could not load the affected quantities.",
    },
    success: {
      DISPOSE: "All current product quantities were disposed and removed from company inventory.",
      RETURN_TO_VENDOR: "All current product quantities were handed over and removed from company inventory.",
    },
    title: "Handle affected quantities",
    noStock: "There is no current stock for this product in locations you can read.",
    affectedStock: "Current quantities covered by this decision",
    total: "Total: {{quantity}}{{secondary}}",
    actions: {
      disposeAll: "Dispose entire product stock",
      returnAll: "Return entire product stock to vendor / manufacturer",
    },
    confirm: {
      disposeTitle: "Confirm disposal of all product stock",
      returnTitle: "Confirm return of all product stock",
      scope: "This decision will apply to all current stock across {{count}} location(s) · {{quantity}}{{secondary}}.",
      disposeButton: "Confirm disposal of all quantities",
      returnButton: "Confirm handover of all quantities",
    },
    fields: {
      reason: "Reason",
      method: "Disposal method (optional)",
      evidence: "Evidence reference (optional)",
      recipientName: "Recipient / vendor / manufacturer name",
      handoverReference: "Handover reference",
    },
  },
} as const;
