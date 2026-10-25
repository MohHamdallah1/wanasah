import i18n from "@/i18n";
import { apiErrorCode, apiErrorMessage } from "@/lib/apiErrors";

const vehicleErrorKeys: Record<string, string> = {
  VEHICLE_PLATE_CONFLICT: "representativesVehicles.vehicles.errors.plateConflict",
  VEHICLE_NOT_FOUND: "representativesVehicles.vehicles.errors.notFound",
  VEHICLE_IDEMPOTENCY_CONFLICT: "representativesVehicles.vehicles.errors.idempotencyConflict",
  VEHICLE_CREATE_CONFLICT: "representativesVehicles.vehicles.errors.concurrentConflict",
  VEHICLE_UPDATE_CONFLICT: "representativesVehicles.vehicles.errors.concurrentConflict",
  VEHICLE_VERSION_CONFLICT: "representativesVehicles.vehicles.errors.versionConflict",
  VEHICLE_ALREADY_ACTIVE: "representativesVehicles.vehicles.errors.alreadyActive",
  VEHICLE_ALREADY_INACTIVE: "representativesVehicles.vehicles.errors.alreadyInactive",
  VEHICLE_DEACTIVATION_BLOCKED: "representativesVehicles.vehicles.errors.deactivationBlocked",
  VEHICLE_MAINTENANCE_BLOCKED: "representativesVehicles.vehicles.errors.maintenanceBlocked",
  VEHICLE_MAINTENANCE_SCHEDULE_REQUIRED: "representativesVehicles.vehicles.errors.maintenanceScheduleRequired",
  VEHICLE_OIL_CHANGE_TARGET_INVALID: "representativesVehicles.vehicles.errors.oilChangeTargetInvalid",
  VEHICLE_CUSTODY_LOCATION_MISSING: "representativesVehicles.vehicles.errors.custodyUnavailable",
  VEHICLE_CUSTODY_LOCATION_AMBIGUOUS: "representativesVehicles.vehicles.errors.custodyUnavailable",
  VEHICLE_CUSTODY_LOCATION_INCONSISTENT: "representativesVehicles.vehicles.errors.custodyUnavailable",
  VEHICLE_CUSTODY_CREATE_ORDER_INVALID: "representativesVehicles.vehicles.errors.custodyUnavailable",
  VEHICLE_CURSOR_INVALID: "representativesVehicles.vehicles.errors.cursorInvalid",
  VEHICLE_SEARCH_INVALID: "representativesVehicles.vehicles.searchHint",
  VEHICLE_REQUEST_ID_INVALID: "errors.codes.VALIDATION_ERROR",
  VEHICLE_UPDATE_EMPTY: "representativesVehicles.vehicles.form.noChanges",
  VEHICLE_UPDATE_FIELD_INVALID: "errors.codes.VALIDATION_ERROR",
  VEHICLE_PLATE_INVALID: "representativesVehicles.vehicles.form.plateInvalid",
  VEHICLE_TYPE_INVALID: "representativesVehicles.vehicles.form.typeInvalid",
  VEHICLE_FIELD_INVALID: "errors.codes.VALIDATION_ERROR",
  VEHICLE_VERSION_INVALID: "errors.codes.VALIDATION_ERROR",
  VEHICLE_MAINTENANCE_STATUS_INVALID: "representativesVehicles.vehicles.form.maintenanceInvalid",
  VEHICLE_LOAD_PERMISSION_DENIED: "representativesVehicles.vehicles.load.permissionDenied",
  VEHICLE_LOAD_OWNED_BY_WORKFLOW: "representativesVehicles.vehicles.load.workflowOwned",
  VEHICLE_LOAD_IDEMPOTENCY_CONFLICT: "representativesVehicles.vehicles.errors.idempotencyConflict",
  VEHICLE_LOAD_CURSOR_INVALID: "representativesVehicles.vehicles.errors.cursorInvalid",
  VEHICLE_CUSTODY_LOCATION_UNAVAILABLE: "representativesVehicles.vehicles.errors.custodyUnavailable",
  VEHICLE_NOT_OPERATIONAL: "representativesVehicles.vehicles.load.notOperational",
};

export function vehicleErrorMessage(error: unknown, fallback: string): string {
  const code = apiErrorCode(error);
  const key = code ? vehicleErrorKeys[code] : undefined;
  return key ? i18n.t(key) : apiErrorMessage(error, fallback);
}
