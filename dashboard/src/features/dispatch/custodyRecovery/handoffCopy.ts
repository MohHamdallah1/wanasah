const words = {
  ar: {
    title:"مراجعة واعتماد عهدة السيارة", loading:"جارٍ جلب حالة العهدة من الخادم…",
    stock:"البضاعة المطلوب جردها", empty:"لا توجد بضاعة مسجلة", recipient:"المندوب المستلم",
    choose:"اختر المندوب", send:"إرسال طلب استلام العهدة", change:"تغيير المندوب",
    cancel:"إلغاء الطلب", confirmCancel:"تأكيد إلغاء الطلب", abort:"تراجع",
    cancelWarning:"إلغاء الطلب يسحب موافقة المندوب ويمنع اعتمادها. هل تريد المتابعة؟",
    awaiting:"بانتظار رد المندوب", confirmed:"المندوب أكد الجرد", declined:"رفض الاستلام",
    expired:"انتهت صلاحية طلب الاستلام", cancelled:"تم إلغاء طلب الاستلام",
    committed:"تم اعتماد العهدة", approve:"اعتماد العهدة",
    refresh:"تحديث حالة الطلب", reload:"إعادة فحص البضاعة",
    history:"سجل العهدة", unknownHistory:"مسؤول سابق غير موثق",
    approvedBy:"اعتمدها", since:"منذ", until:"حتى", logged:"سُجلت للمراجعة", noneHistory:"لا توجد سجلات سابقة",
    unavailableHistory:"تعذّر جلب سجل العهدة", noAccess:"ليس لديك صلاحية إدارة العهدة.",
    blocked:"لا يمكن إرسال طلب قبل حل مشكلة أهلية السيارة أو المخزون.",
    offline:"تعذّر الوصول إلى الخادم. لا يُعتبر الطلب مُرسلًا أو معتمدًا.",
    stale:"تغيّر المخزون أو الصلاحية. افحص البيانات الحقيقية ثم أعد المحاولة.",
    denied:"انتهت صلاحيتك أو لا يحق لك إدارة هذه السيارة.",
    generic:"تعذّر التحقق من العملية. حدّث الحالة قبل أي طلب جديد.",
    status:"الحالة", lot:"التشغيلة", noLot:"بدون تشغيلة", expiry:"الصلاحية",
    quantity:"الكمية", reserved:"محجوز", noMovement:"الاعتماد لا ينقل أي بضاعة.",
    close:"إغلاق", pendingAction:"لن يتم إرسال طلب جديد قبل تأكيد إلغاء الطلب الحالي.",
  },
  en: {
    title:"Review vehicle custody", loading:"Checking custody status with server…",
    stock:"Physical stock to count", empty:"No recorded vehicle stock", recipient:"Receiving representative",
    choose:"Choose representative", send:"Send custody receipt request", change:"Change representative",
    cancel:"Cancel request", confirmCancel:"Confirm cancellation", abort:"Back",
    cancelWarning:"Cancellation revokes the representative's response and prevents approval. Continue?",
    awaiting:"Waiting for representative's response", confirmed:"Representative confirmed physical count",
    declined:"Receipt declined", expired:"Receipt request expired", cancelled:"Receipt request cancelled",
    committed:"Custody approved", approve:"Approve custody",
    refresh:"Refresh request status", reload:"Recheck stock",
    history:"Custody history", unknownHistory:"Previous custodian not documented",
    approvedBy:"Approved by", since:"Since", until:"Until", logged:"Review recorded", noneHistory:"No earlier custody records",
    unavailableHistory:"Could not load custody history", noAccess:"You lack vehicle custody authority.",
    blocked:"Resolve vehicle eligibility or stock review before requesting custody.",
    offline:"Server unavailable. Nothing has been sent or approved.",
    stale:"Stock or authority changed. Check real inventory before retrying.",
    denied:"Your permission or vehicle scope was denied.",
    generic:"Could not verify the operation. Refresh before starting a new request.",
    status:"Status", lot:"Lot", noLot:"No printed lot", expiry:"Expiry",
    quantity:"Quantity", reserved:"Reserved", noMovement:"Approval does not move any stock.",
    close:"Close", pendingAction:"A new request cannot be sent until server cancellation is confirmed.",
  },
} as const;
export const handoffCopy=(language:string)=>language.toLowerCase().startsWith("ar")?words.ar:words.en;
export const handoffError=(error:unknown,language:string)=>{
  const copy=handoffCopy(language), detail=error as {status?:number;code?:string};
  const status=detail?.status;
  const code=(detail?.code||"")+" "+String(error);
  if (status===401||status===403||/FORBIDDEN|DENIED|REVOKED/.test(code)) return copy.denied;
  if (/EXPIRED/.test(code))return copy.expired;
  if (status===409||status===422||/STALE|REVISION|SNAPSHOT/.test(code))return copy.stale;
  return copy.offline;
};
