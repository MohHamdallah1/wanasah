/** D11: presentation of the server's advisory, never a Pricing/Tax calculator. */
export const PREFLIGHT_AREAS = [
  "pricing", "tax", "rounding", "offers", "warehouse", "vehicle",
  "driver", "zone", "session", "route", "custody",
] as const;

export type PreflightArea = typeof PREFLIGHT_AREAS[number];
export type PreflightCheck = {
  ready: boolean;
  code: string;
  context: Record<string, unknown>;
};
export type CommercialPreflight = {
  ready: boolean;
  currency_code: string | null;
  advisory: true;
  checks: Record<PreflightArea, PreflightCheck>;
};
export type PreflightSelection = {
  zoneId: string;
  driverId: string;
  vehicleId: string;
  warehouseId: string;
};

export function preflightSelectionValid(selection: PreflightSelection): boolean {
  return Object.values(selection).every(value => /^[1-9]\d*$/.test(value) &&
    Number.isSafeInteger(Number(value)));
}

export function preflightUrl(selection: PreflightSelection): string {
  if (!preflightSelectionValid(selection)) throw new Error("D11_SELECTION_INVALID");
  return "/dispatch/route/commercial-preflight?" + new URLSearchParams({
    zone_id: selection.zoneId,
    driver_id: selection.driverId,
    vehicle_id: selection.vehicleId,
    source_location_id: selection.warehouseId,
  }).toString();
}

export function parseCommercialPreflight(raw: unknown): CommercialPreflight {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("D11_PREFLIGHT_INVALID");
  const value = raw as Record<string, unknown>;
  if (value.advisory !== true || typeof value.ready !== "boolean" ||
      !value.checks || typeof value.checks !== "object" ||
      Array.isArray(value.checks)) throw new Error("D11_PREFLIGHT_INVALID");
  const checks = value.checks as Record<string, unknown>;
  for (const area of PREFLIGHT_AREAS) {
    const row = checks[area];
    if (!row || typeof row !== "object" || Array.isArray(row)) throw new Error("D11_PREFLIGHT_INVALID");
    const entry = row as Record<string, unknown>;
    if (typeof entry.ready !== "boolean" || typeof entry.code !== "string" ||
        !entry.code || !entry.context || typeof entry.context !== "object" ||
        Array.isArray(entry.context)) throw new Error("D11_PREFLIGHT_INVALID");
  }
  if (value.ready !== PREFLIGHT_AREAS.every(area =>
    (checks[area] as PreflightCheck).ready)) throw new Error("D11_PREFLIGHT_INVALID");
  if (value.currency_code !== null && (typeof value.currency_code !== "string" ||
      !/^[A-Z]{3}$/.test(value.currency_code))) throw new Error("D11_PREFLIGHT_INVALID");
  return value as CommercialPreflight;
}

const groups: Record<PreflightArea, [string, string]> = {
  pricing: ["الأسعار", "Prices"], tax: ["الضرائب", "Taxes"],
  rounding: ["التقريب", "Rounding"], offers: ["العروض", "Offers"],
  warehouse: ["مستودع المصدر", "Source warehouse"],
  vehicle: ["المركبة", "Vehicle"], driver: ["المندوب", "Representative"],
  zone: ["المنطقة", "Zone"], session: ["جلسة المندوب", "Representative session"],
  route: ["تعارض الخطوط", "Route assignment"],
  custody: ["عهدة المركبة", "Vehicle custody"],
};

const messages: Record<string, [string, string, string | null]> = {
  PRICE_NOT_RESOLVED: [
    "انشر قائمة أسعار معتمدة، ثم فعّل تعيين قائمة أسعار ساري المفعول للمتجر أو الشركة.",
    "Publish an approved price list and activate an effective company/shop price assignment.", "/products",
  ],
  COMMERCIAL_CURRENCY_INVALID: [
    "صحح عملة الشركة قبل اعتماد الأسعار أو الإطلاق.",
    "Correct the company currency before publishing prices or launching routes.", null,
  ],
  TAX_CONFIGURATION_REQUIRED: [
    "انشر إعداد الضريبة المعتمد في القواعد التجارية؛ نسبة 0% المنشورة صالحة ولا تُعامل كغياب للضريبة.",
    "Publish the tax setup in Commercial Rules. A published 0% tax is valid, but a missing publication is not.", "/commercial-rules",
  ],
  COMMERCIAL_ROUNDING_NOT_CONFIGURED: [
    "انشر سياسة تقريب عملة الشركة في القواعد التجارية قبل إطلاق الخط.",
    "Publish the company-currency rounding policy in Commercial Rules before launch.", "/commercial-rules",
  ],
  COMMERCIAL_ROUNDING_CONFLICT: [
    "راجع تعارض سياسات التقريب المنشورة لدى مسؤول القواعد التجارية.",
    "Resolve conflicting published rounding policies in Commercial Rules.", "/commercial-rules",
  ],
  COMMERCIAL_POLICY_CURRENCY_INVALID: [
    "صحح تعارض العملة بين الشركة وسياسة التقريب المنشورة.",
    "Correct the company currency / published rounding-policy mismatch.", "/commercial-rules",
  ],
  SOURCE_WAREHOUSE_INVALID: [
    "اختر مستودع مصدر فعالاً ومخوّلاً لشركتك.",
    "Select an active, authorized source warehouse.", "/inventory",
  ],
  SOURCE_WAREHOUSE_AUDIT_LOCK: [
    "المستودع تحت جرد شامل؛ أنهِ الجرد أو اعتمده لتحرير القفل ثم أعد التحقق.",
    "This warehouse has an active full stocktake. Finish/approve the stocktake to release the lock, then recheck.", "/inventory",
  ],
  VEHICLE_NOT_OPERATIONAL: [
    "فعّل المركبة أو أنهِ حالة الصيانة قبل الإطلاق.",
    "Activate the vehicle and clear its maintenance hold before launch.", "/representatives-vehicles",
  ],
  VEHICLE_CUSTODY_UNAVAILABLE: [
    "أصلح موقع عهدة المركبة المرتبط بها قبل الإطلاق.",
    "Repair the vehicle's canonical custody location before launch.", "/representatives-vehicles",
  ],
  VEHICLE_CUSTODY_LOCATION_MISSING: [
    "أنشئ موقع عهدة واحداً سليماً للمركبة قبل الإطلاق.",
    "Set up exactly one valid vehicle custody location before launch.", "/representatives-vehicles",
  ],
  VEHICLE_RESERVATIONS_PENDING: [
    "سوِّ الحجوزات أو الحوالات المعلقة على المركبة قبل إطلاق الخط.",
    "Resolve pending vehicle reservations or transfers before launching.", "/dispatch",
  ],
  DRIVER_UNAVAILABLE: [
    "اختر مندوباً نشطاً ومصرحاً له بالعمل.",
    "Select an active, authorized representative.", "/representatives-vehicles",
  ],
  ZONE_UNAVAILABLE: [
    "اختر منطقة نشطة غير مؤرشفة.",
    "Select an active, non-archived zone.", "/dispatch",
  ],
  DRIVER_SESSION_ACTIVE: [
    "المندوب في جلسة عمل حالية؛ أنهِ الجلسة أو عدّل خطه القائم بدلاً من إطلاق خط جديد.",
    "The representative has an active work session. End it or adjust the existing route instead.", "/dispatch",
  ],
  DRIVER_SETTLEMENT_REQUIRED: [
    "سوِّ جلسة المندوب السابقة مالياً قبل إطلاق يوم جديد.",
    "Settle the representative's previous session before starting a new route.", "/dispatch",
  ],
  ROUTE_ALREADY_ASSIGNED: [
    "المنطقة أو المندوب أو المركبة مرتبطة بخط فعال أو معلق؛ أغلق التعارض أولاً.",
    "The zone, representative or vehicle is assigned to an active/pending route. Resolve that route first.", "/dispatch",
  ],
};
const unknown = [
  "تعذر اعتماد هذا البند من البيانات الفعلية. راجع إعداداته ثم أعد التحقق.",
  "This item cannot be verified from current records. Review its settings and recheck.",
  null,
] as const;

export function preflightLabel(lang: string, area: PreflightArea): string {
  return groups[area][lang.toLowerCase().startsWith("ar") ? 0 : 1];
}
export function preflightReason(lang: string, code: string): { text: string; path: string | null } {
  const row = messages[code] ?? unknown;
  return { text: row[lang.toLowerCase().startsWith("ar") ? 0 : 1], path: row[2] };
}
export function preflightCopy(lang: string, key:
  "title" | "ready" | "checking" | "blocked" | "choose" | "retry" |
  "unavailable" | "denied" | "fix" | "review" | "launch" | "refresh"): string {
  const ar = {
    title: "جاهزية إطلاق خط السير", ready: "التحقق ناجح — جميع متطلبات الإطلاق مستوفاة حالياً.",
    checking: "جاري التحقق من الإعدادات الحالية للشركة والمركبة والمستودع...",
    blocked: "الإطلاق ممنوع حتى معالجة البنود التالية:",
    choose: "اختر المنطقة والمندوب والمركبة ومستودع المصدر لعرض جاهزية الإطلاق.",
    retry: "أعد المحاولة بعد تصحيح الإعداد.",
    unavailable: "تعذّر التحقق من جاهزية الإطلاق. لم يتم إرسال أي طلب؛ أعد التحقق.",
    denied: "انتهت الصلاحية أو تغير الحساب. أعد تسجيل الدخول أو اطلب صلاحية إطلاق الخط.",
    fix: "اذهب للإعداد", review: "تم التحقق", launch: "اعتماد وإطلاق خط السير", refresh: "إعادة التحقق",
  };
  const en: typeof ar = {
    title: "Route launch readiness", ready: "Checks passed — launch requirements are currently met.",
    checking: "Checking current company, vehicle and warehouse policies...",
    blocked: "Launch is blocked until these issues are resolved:",
    choose: "Select a zone, representative, vehicle and source warehouse to check launch readiness.",
    retry: "Recheck after fixing the issue.",
    unavailable: "Readiness could not be verified. Nothing was submitted; recheck.",
    denied: "Access was revoked or the account changed. Sign in again or request route launch permission.",
    fix: "Open settings", review: "Verified", launch: "Confirm and launch route", refresh: "Recheck readiness",
  };
  return (lang.toLowerCase().startsWith("ar") ? ar : en)[key];
}
