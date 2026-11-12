/** M05 bilingual business copy lives with this bounded feature, never in
 * route authority, API payloads, or the oversized DispatchBoard view.
 */
const labels = {
  ar: {
    title: "إدارة تشغيل الخط",
    driver: "المندوب",
    vehicle: "السيارة",
    postpone: "تأجيل الخط",
    resume: "استئناف الخط",
    close: "إغلاق الخط",
    retry: "التحقق وإعادة محاولة الطلب الأصلي",
    noEvidence: "لم يكتمل التحقق من التعيين الحالي والعهدة. لا يمكن تنفيذ الأمر.",
    separatedStock: "تغيير الخط أو السيارة لا ينقل البضاعة أو يحوّل العهدة.",
    success: "تم تنفيذ الأمر وتأكيده من الخادم.",
    conflict: "تغيّرت بيانات الخط أو العهدة. راجع الطلب الأصلي قبل أي تغيير.",
    unknown: "لم يتأكد رد الخادم. تم حفظ الطلب الأصلي لإعادة المحاولة دون تكرار.",
    accessDenied: "تعذر التحقق من صلاحياتك الحالية.",
  },
  en: {
    title: "Route execution",
    driver: "Representative",
    vehicle: "Vehicle",
    postpone: "Postpone route",
    resume: "Resume route",
    close: "Close route",
    retry: "Verify and retry original command",
    noEvidence: "Current assignment and custody have not been verified. This action is unavailable.",
    separatedStock: "Changing routes or vehicles does not move stock or transfer custody.",
    success: "The server confirmed the route command.",
    conflict: "Route or custody evidence changed. Review the original command before changing anything.",
    unknown: "Server outcome is unconfirmed. The original command is saved for safe retry.",
    accessDenied: "Your current permission could not be verified.",
  },
} as const;

export const lifecycleCopy = (language: string) =>
  language.toLowerCase().startsWith("ar") ? labels.ar : labels.en;
