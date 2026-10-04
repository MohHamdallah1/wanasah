export const batchFocus = {
  ar: {
    title: "الدفعة ومواقع كمياتها",
    back: "العودة إلى المخزون",
    singleSource: "مصدر الكمية المتاح: {{source}}",
    multipleSources: "الكميات موزعة على {{count}} مواقع متاحة لك. اختر الإجراء من المصدر المطلوب؛ لم يُحدد مستودع تلقائياً.",
    noReadableStock: "لا توجد كميات متاحة للعرض لهذه الدفعة حالياً.",
    scopeMismatch: "الدفعة لا تطابق المنتج المحدد. لم يُنفذ أي إجراء.",
    noExpiry: "لا يوجد تاريخ انتهاء",
    changeDisposition: "مراجعة قرار الدفعة",
  },
  en: {
    title: "Batch and stock sources",
    back: "Back to Inventory",
    singleSource: "Available stock source: {{source}}",
    multipleSources: "Stock is distributed across {{count}} sources you can read. Choose an action at its source; no warehouse was selected automatically.",
    noReadableStock: "No stock is currently available for you to view for this batch.",
    scopeMismatch: "The batch does not match the selected product. No action was executed.",
    noExpiry: "No expiry date",
    changeDisposition: "Review batch decision",
  },
} as const;
