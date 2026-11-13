const reasons: Record<string, [string, string]> = {
  ZONE_INACTIVE: ["المنطقة غير نشطة", "Inactive zone"],
  ZONE_ROUTE_RESERVED: ["المنطقة محجوزة بخط قيد التشغيل أو متوقف مؤقتًا", "Zone assigned to an active or paused route"],
  ZONE_POSTPONED_RESERVED: ["المنطقة مؤجلة ومحجوزة؛ المندوب والسيارة محرران", "Postponed zone stays reserved; representative and vehicle are released"],
  REPRESENTATIVE_INACTIVE: ["المندوب غير نشط", "Inactive representative"],
  REPRESENTATIVE_FIELD_UNVERIFIED: ["هوية المندوب الميدانية غير معتمدة", "Field representative identity is not verified"],
  REPRESENTATIVE_ON_ROUTE: ["المندوب مرتبط بخط نشط أو متوقف مؤقتًا", "Representative assigned to an active or paused route"],
  PREVIOUS_SESSION_UNSETTLED: ["جلسة المندوب السابقة لم تسوَّ بالكامل ماليًا ومخزنيًا", "Prior WorkSession needs full cash and vehicle-stock settlement"],
  VEHICLE_NOT_OPERATIONAL: ["السيارة متوقفة أو تحت الصيانة", "Vehicle inactive or under maintenance"],
  VEHICLE_LOCATION_INVALID: ["موقع عهدة السيارة غير صالح أو غير محدد", "Vehicle custody location is invalid"],
  VEHICLE_ON_ROUTE: ["السيارة مرتبطة بخط نشط أو متوقف مؤقتًا", "Vehicle assigned to an active or paused route"],
  VEHICLE_CUSTODY_UNACCEPTED: ["عهدة السيارة الحالية غير معتمدة", "Current vehicle custody is not accepted"],
  CUSTODY_REQUIRES_REASSIGNMENT: ["عهدة السيارة لمندوب آخر؛ يلزم اعتماد نقلها أولًا", "Custody belongs to another representative; approve reassignment first"],
  WAREHOUSE_INACTIVE: ["المستودع غير نشط", "Inactive warehouse"],
  WAREHOUSE_AUDIT_LOCK: ["المستودع تحت قفل الجرد", "Warehouse stocktake lock is active"],
  NO_EXECUTE_PERMISSION: ["لا تملك صلاحية تشغيل هذا المورد", "Your account cannot execute operations for this resource"],
};
export function resourceReason(code: string, ar: boolean) {
  return reasons[code]?.[ar ? 0 : 1] ||
    (ar ? "هذا المورد غير متاح؛ تحقّق من صلاحيات التشغيل" : "Resource unavailable; verify operational authority");
}
