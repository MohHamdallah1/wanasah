export const dispatchRouteSafety = {
  ar: {
    followUp: "متابعة خط السير",
    transfer: "تحويل لمندوب آخر",
    driver: "المندوب",
    vehicle: "السيارة",
    confirmRouteOnly: "تأكيد حالة الخط والتعيين",
    sessionLocked: "الجلسة مرتبطة بهذا الخط؛ لا يمكن تغيير المندوب أو السيارة.",
    sessionEnded: "انتهت جلسة العمل؛ لا يمكن إعادة تشغيل الخط من هنا.",
    separateStock: "تغيير حالة الخط أو تعيينه لا يعدّل البضاعة. لتعديل حمولة السيارة استخدم العملية المستقلة بالكميات الدقيقة مع مراجعة وتأكيد.",
    adjustCurrentVehicle: "اعتمد تغيير السيارة أولاً، ثم عدّل حمولة السيارة المرتبطة بالخط.",
  },
  en: {
    followUp: "Manage route",
    transfer: "Transfer to another representative",
    driver: "Representative",
    vehicle: "Vehicle",
    confirmRouteOnly: "Confirm route status and assignment",
    sessionLocked: "This route is bound to a work session; representative and vehicle cannot change.",
    sessionEnded: "The work session has ended; this route cannot be restarted here.",
    separateStock: "Route status and assignment never change vehicle stock. Use the separate Adjust Load operation with precise quantities, review, and confirmation.",
    adjustCurrentVehicle: "Confirm the vehicle reassignment first, then adjust the route's assigned vehicle.",
  },
} as const;
