/** Language keys scoped to this bounded C03 workflow. No backend decision uses text. */
const words = {
  en:{
    title:"Review vehicle custody",
    info:"The manager and receiving representative must approve separately. No stock moves.",
    noAccess:"You do not have the required permission. Ask an authorized manager.",
    loading:"Verifying vehicle and inventory…", vehicle:"Vehicle",
    first:"This vehicle has unconfirmed historical stock. Count and accept it together.",
    none:"This vehicle has stock but no custody record. Signed first acceptance is required.",
    other:"Another representative holds accepted custody. A signed handoff is required.",
    invalid:"Custody evidence requires investigation.", blocked:"Settle the active route or open session first.",
    stale:"Stock or custody changed. Review and count again.",
    expired:"The private handoff expired. Review again.", denied:"The required permissions were denied.",
    unknown:"No confirmed server response. Check the original operation before trying again.",
    stock:"Physical stock to count", noStock:"No recorded vehicle stock",
    batch:"Batch", exp:"Expiry", base:"Base quantity", reserved:"Reserved", status:"Status",
    rep:"Receiving representative", select:"Choose representative", prepare:"Prepare handoff",
    handoff:"Send the private handoff to the intended representative (valid for 15 minutes).",
    copyHandoff:"Copy private handoff", copied:"Copied. Share privately with the intended person only.",
    proof:"Paste the signed receipt returned by the FIELD app",
    approve:"Approve verified custody", verify:"Verify / retry original request",
    refresh:"Recheck inventory", complete:"Custody accepted. Vehicle eligibility may now be refreshed.",
    safe:"Never transfers or unloads stock.", close:"Close", missing:"Unable to verify current custody.",
  },
  ar:{
    title:"مراجعة واعتماد عهدة السيارة",
    info:"يتطلب اعتماد المدير والمندوب المستلم بشكل مستقل. لا تتحرك أي بضاعة.",
    noAccess:"لا تملك صلاحية اعتماد العهدة. راجع المدير المخوّل.",
    loading:"جارٍ التحقق من العهدة والمخزون…", vehicle:"السيارة",
    first:"توجد بضاعة تاريخية بلا مسؤول معتمد. جردها مع المندوب قبل الاعتماد.",
    none:"السيارة محمّلة ولا يوجد سجل عهدة. يلزم اعتماد أولي موقّع.",
    other:"العهدة معتمدة لمندوب آخر. يلزم تسليم مسؤولية موقّع.",
    invalid:"إثبات العهدة يحتاج إلى مراجعة.", blocked:"سوِّ الخط النشط أو الجلسة غير المغلقة أولًا.",
    stale:"تغير المخزون أو سجل العهدة. أعد المراجعة والجرد.",
    expired:"انتهت صلاحية طلب الاستلام الخاص. أعد المراجعة.",
    denied:"الصلاحيات المطلوبة غير متاحة.", unknown:"لم يتأكد رد الخادم. تحقق من العملية الأصلية قبل المحاولة.",
    stock:"المخزون المطلوب جرده فعليًا", noStock:"لا يوجد مخزون مسجل",
    batch:"الدفعة", exp:"الصلاحية", base:"الكمية بالوحدة الأساسية", reserved:"محجوز", status:"الحالة",
    rep:"المندوب المستلم", select:"اختر المندوب", prepare:"تجهيز التسليم",
    handoff:"أرسل طلب التسليم الخاص للمندوب المعني فقط (صالح لمدة ١٥ دقيقة).",
    copyHandoff:"نسخ طلب التسليم الخاص", copied:"تم النسخ. أرسله للمندوب المعني بطريقة خاصة.",
    proof:"ألصق إثبات الاستلام الموقّع من تطبيق FIELD",
    approve:"اعتماد العهدة الموثقة", verify:"تحقق / أعد نفس الطلب",
    refresh:"إعادة فحص المخزون", complete:"تم اعتماد العهدة. يمكن تحديث أهلية السيارة الآن.",
    safe:"هذه العملية لا تحمل أو تنزل أي بضاعة.", close:"إغلاق", missing:"تعذّر التحقق من العهدة.",
  },
} as const;
export const custodyCopy = (language:string) =>
  language.toLowerCase().startsWith("ar")?words.ar:words.en;
export const custodyReason=(code:string,lang:string)=>{
  const t=custodyCopy(lang);
  if(code==="CUSTODY_STOCK_WITHOUT_EPOCH")return t.none;
  if(code==="CUSTODY_NEEDS_REVIEW")return t.first;
  if(code==="CUSTODY_REQUIRES_REASSIGNMENT")return t.other;
  if(/LIVE_ROUTE|UNSETTLED|IN_USE/.test(code))return t.blocked;
  if(/STALE|REVISION|MODE_CHANGED/.test(code))return t.stale;
  if(/EXPIRED|PROOF_INVALID/.test(code))return t.expired;
  if(/DENIED|CAPABILITY|FORBIDDEN|REVOKED/.test(code))return t.denied;
  return t.missing;
};
