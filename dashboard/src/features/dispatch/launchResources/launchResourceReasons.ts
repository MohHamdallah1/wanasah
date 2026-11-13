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
  VEHICLE_CUSTODY_UNACCEPTED: ["إثبات عهدة السيارة غير مكتمل؛ يلزم التحقق والاعتماد", "Vehicle custody evidence is incomplete; review and approve"],
  CUSTODY_NEEDS_REVIEW: ["مسؤول عهدة السيارة الحالية غير معروف؛ يلزم جردها واعتماد الاستلام الأولي", "Current vehicle stock custodian is unknown; count and sign first acceptance"],
  CUSTODY_STOCK_WITHOUT_EPOCH: ["توجد بضاعة في السيارة بلا سجل عهدة موثوق؛ يلزم مراجعتها قبل الإطلاق", "Vehicle holds stock without a trusted custody record; investigate before launch"],
  CUSTODY_NON_FIELD_CUSTODIAN: ["العهدة مثبتة لجهة غير ميدانية؛ يلزم إقفالها أو مراجعة نقلها رسميًا", "Custody belongs to a non-field holder; resolve the formal handoff"],
  CUSTODY_REQUIRES_REASSIGNMENT: ["عهدة السيارة معتمدة لمندوب مختلف؛ يلزم إثبات نقل المسؤولية إليه أو منه", "Custody is accepted by another representative; a signed responsibility handoff is required"],
  WAREHOUSE_INACTIVE: ["المستودع غير نشط", "Inactive warehouse"],
  WAREHOUSE_AUDIT_LOCK: ["المستودع تحت قفل الجرد", "Warehouse stocktake lock is active"],
  NO_EXECUTE_PERMISSION: ["لا تملك صلاحية تشغيل هذا المورد", "Your account cannot execute operations for this resource"],
};
export function resourceReason(code: string, ar: boolean) {
  return reasons[code]?.[ar ? 0 : 1] ||
    (ar ? "هذا المورد غير متاح؛ تحقّق من صلاحيات التشغيل" : "Resource unavailable; verify operational authority");
}
