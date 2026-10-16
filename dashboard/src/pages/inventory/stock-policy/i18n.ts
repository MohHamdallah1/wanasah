import { useTranslation } from "react-i18next";

const copy = {
  ar: {
    title: "سياسة مدة الصلاحية الفعالة",
    readOnly: "عرض توضيحي فقط في V1 — لا توجد صلاحية كتابة مستقلة لهذه السياسة حالياً.",
    chooseOne: "اختر منتجاً واحداً لعرض شرط مدة الصلاحية والدفعات المرتبطة به.",
    requirement: "الحد الأدنى المتبقي المطلوب للبيع",
    noRequirement: "لا يوجد حد أدنى إضافي لمدة الصلاحية (0 يوم).",
    days: "{{count}} يوم",
    warningSeparate: "تنبيه قرب الانتهاء تفضيل عرض منفصل ولا يغيّر نتيجة قابلية البيع.",
    sampleTitle: "أقرب الدفعات — نتيجة الخادم",
    remaining: "المتبقي",
    noExpiry: "بدون تاريخ صلاحية",
    reasonCode: "رمز الخادم",
    noBatches: "لا توجد دفعات حالية لهذا المنتج في المستودع.",
    loadError: "تعذر تحميل شرح سياسة الصلاحية.",
    retry: "إعادة المحاولة",
    costRule: "أي تكلفة تظهر في شاشات المخزون تُعرض فقط من دليل أعاده الخادم؛ لا يتم حساب تكلفة داخل React.",
  },
  en: {
    title: "Effective shelf-life policy",
    readOnly: "Read-only V1 explainability — no dedicated shelf-life write authority exists today.",
    chooseOne: "Select one product to inspect its shelf-life requirement and related batches.",
    requirement: "Minimum remaining shelf life required for sale",
    noRequirement: "No additional shelf-life minimum applies (0 days).",
    days: "{{count}} days",
    warningSeparate: "The expiring-soon warning is a separate display preference and never changes sellability.",
    sampleTitle: "Nearest batches — server result",
    remaining: "Remaining",
    noExpiry: "No expiry date",
    reasonCode: "Server code",
    noBatches: "No current batches for this product at the warehouse.",
    loadError: "Could not load shelf-life policy explainability.",
    retry: "Retry",
    costRule: "Any inventory cost shown elsewhere is rendered only from server-returned evidence; React does not calculate cost.",
  },
} as const;

export function useShelfLifePolicyCopy() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language ?? "ar";
  const isArabic = language.toLowerCase().startsWith("ar");

  return {
    t,
    copy: isArabic ? copy.ar : copy.en,
    dir: isArabic ? ("rtl" as const) : ("ltr" as const),
    locale: isArabic ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn",
  };
}
