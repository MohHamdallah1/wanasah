/** Dispatch-only locale resources. Presentation copy does not gate access or change route state. */
export const dispatchChromeCopy = {
  ar: {
    tablist: "أقسام إدارة التوزيع",
    tabs: {
      routes: "الخطوط النشطة",
      launch: "إطلاق خط جديد",
      zones: "هيكلة المناطق",
    },
    shortages: "طلبات ونواقص",
    bulkSchedule: "الجدولة الشاملة",
    workingZones: "مناطق قيد العمل (الخطوط النشطة)",
    showPostponed: "عرض المؤجل",
  },
  en: {
    tablist: "Dispatch sections",
    tabs: {
      routes: "Active routes",
      launch: "Launch new route",
      zones: "Zone structure",
    },
    shortages: "Requests & shortages",
    bulkSchedule: "Bulk scheduling",
    workingZones: "Zones in progress (active routes)",
    showPostponed: "Show postponed",
  },
} as const;

export function getDispatchChromeCopy(language: string) {
  return dispatchChromeCopy[language.startsWith("ar") ? "ar" : "en"];
}
