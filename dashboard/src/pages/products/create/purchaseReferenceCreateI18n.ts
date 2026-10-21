import i18n from "@/i18n";

const copy = {
  en: {
    enable: "Add a purchase-cost reference (optional)",
    hint: "Purchase cost is independent from the sale prices above. This reference does not change inventory value.",
    amount: "Purchase reference amount",
    uom: "Purchase unit",
    currency: "Company currency: {{currency}}",
    invalid: "Enter an exact nonnegative purchase amount with up to six decimal places and select its purchase unit.",
    unavailable: "Purchase reference options are unavailable. You can retry or create the product without a reference.",
    denied: "Purchase-reference manage permission is required. Your entered reference is preserved.",
    changedCurrency: "Company currency changed. Clear the purchase reference and enter it again in the current currency.",
    changedUom: "Select a purchase unit available for this product's current packaging.",
    chooseUom: "Select purchase unit",
    retry: "Retry purchase reference options",
  },
  ar: {
    enable: "إضافة تكلفة شراء مرجعية (اختياري)",
    hint: "تكلفة الشراء مستقلة عن أسعار البيع أعلاه. هذه القيمة المرجعية لا تغيّر تقييم المخزون.",
    amount: "مبلغ تكلفة الشراء المرجعية",
    uom: "وحدة الشراء",
    currency: "عملة الشركة: {{currency}}",
    invalid: "أدخل تكلفة شراء غير سالبة بدقة حتى ست منازل عشرية واختر وحدة الشراء.",
    unavailable: "تعذر تحميل خيارات تكلفة الشراء المرجعية. يمكنك إعادة المحاولة أو إنشاء المنتج دون تكلفة مرجعية.",
    denied: "يلزم إذن إدارة تكلفة الشراء المرجعية. تم الاحتفاظ بالقيمة التي أدخلتها.",
    changedCurrency: "تغيّرت عملة الشركة. امسح تكلفة الشراء المرجعية وأدخلها مجدداً بالعملة الحالية.",
    changedUom: "اختر وحدة شراء متاحة لتعبئة المنتج الحالية.",
    chooseUom: "اختر وحدة الشراء",
    retry: "إعادة تحميل خيارات تكلفة الشراء المرجعية",
  },
};

for (const language of ["ar", "en"] as const) {
  i18n.addResourceBundle(language, "productCreatePurchaseReference", copy[language], true, true);
}
