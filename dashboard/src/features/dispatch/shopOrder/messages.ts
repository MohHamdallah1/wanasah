/** Feature-owned AR/EN message catalog; no locale-specific business decisions. */
const messages = {
  ar: {
    selectedZone: "ترتيب المحلات متاح فقط في منطقة «{zone}».",
    otherZone: "نتائج المناطق الأخرى للعرض فقط؛ اختر منطقتها من القائمة لتعديل ترتيبها.",
    outsideZone: "محل من منطقة أخرى؛ اختر منطقته لتعديل الترتيب.",
    orderInput: "ترتيب {shop} في المنطقة المحددة",
    archiveShop: "أرشفة {shop}",
    cancel: "إلغاء",
    save: "حفظ",
    saving: "جاري الحفظ...",
    edit: "تعديل",
    saved: "تم حفظ ترتيب محلات المنطقة والتحقق منه.",
    nothingChanged: "لا توجد تغييرات في ترتيب المنطقة المحددة لحفظها.",
    verifiedNoChange: "تمت مطابقة ترتيب المنطقة الحالي مع الخادم؛ لا حاجة لإعادة الحفظ.",
    retryConfirm: "التحقق من الحفظ",
    readbackFailed: "نتيجة الحفظ غير مؤكدة. سيتم التحقق من ترتيب المنطقة قبل أي محاولة أخرى.",
    reconcileConflict: "تغيّر ترتيب المنطقة من مستخدم آخر. لم نُعد الحفظ. راجع البيانات أو ألغِ التعديلات وأعد المحاولة.",
    changeZoneFirst: "احفظ أو ألغِ التغييرات أولاً قبل اختيار منطقة أخرى.",
    saveFailed: "تعذّر حفظ الترتيب.",
    cancelFailed: "تعذّر إعادة تحميل المحلات. لم يتم تجاهل التعديلات.",
  },
  en: {
    selectedZone: "Reordering is available only in the selected zone “{zone}”.",
    otherZone: "Matches from other zones are view-only for ordering. Select their zone to reorder them.",
    outsideZone: "Shop in another zone; select that zone to edit its order.",
    orderInput: "Order of {shop} in the selected zone",
    archiveShop: "Archive {shop}",
    cancel: "Cancel",
    save: "Save",
    saving: "Saving...",
    edit: "Edit",
    saved: "Zone shop order saved and verified.",
    nothingChanged: "There are no selected-zone order changes to save.",
    verifiedNoChange: "The current zone order was reconciled with the server; no new write was needed.",
    retryConfirm: "Verify saved order",
    readbackFailed: "Save outcome is unknown. The zone order must be checked before another write.",
    reconcileConflict: "Another operator changed this zone. Nothing was resent. Review the changes or cancel and refresh.",
    changeZoneFirst: "Save or discard changes before choosing another zone.",
    saveFailed: "Could not save shop order.",
    cancelFailed: "Could not reload shops. Your unsaved edits were retained.",
  },
} as const;

export type ShopOrderTextKey = keyof typeof messages.en;
export function shopOrderText(language: string, key: ShopOrderTextKey, values: Record<string, string> = {}): string {
  const strings = language.toLowerCase().startsWith("ar") ? messages.ar : messages.en;
  let value: string = strings[key];
  for (const [name, replacement] of Object.entries(values)) {
    value = value.split(`{${name}}`).join(replacement);
  }
  return value;
}
