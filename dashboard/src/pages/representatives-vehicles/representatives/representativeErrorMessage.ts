import i18n from "@/i18n";
import { apiErrorCode, apiErrorMessage } from "@/lib/apiErrors";

const representativeErrorKeys: Record<string, string> = {
  REPRESENTATIVE_USERNAME_CONFLICT:
    "representativesVehicles.representatives.errors.usernameConflict",
  REPRESENTATIVE_NOT_FOUND:
    "representativesVehicles.representatives.errors.notFound",
  REPRESENTATIVE_IDEMPOTENCY_CONFLICT:
    "representativesVehicles.representatives.errors.idempotencyConflict",
  REPRESENTATIVE_CREATE_CONFLICT:
    "representativesVehicles.representatives.errors.concurrentConflict",
  REPRESENTATIVE_UPDATE_CONFLICT:
    "representativesVehicles.representatives.errors.concurrentConflict",
  REPRESENTATIVE_ALREADY_ACTIVE:
    "representativesVehicles.representatives.errors.alreadyActive",
  REPRESENTATIVE_ALREADY_INACTIVE:
    "representativesVehicles.representatives.errors.alreadyInactive",
  REPRESENTATIVE_DEACTIVATION_BLOCKED:
    "representativesVehicles.representatives.errors.deactivationBlocked",
  REPRESENTATIVE_SESSION_INVALIDATION_REJECTED:
    "representativesVehicles.representatives.errors.sessionInvalidationRejected",
  REPRESENTATIVE_COMPANY_PASSWORD_INVALID:
    "representativesVehicles.representatives.form.passwordInvalid",
  REPRESENTATIVE_COMPANY_PASSWORD_TOO_SHORT:
    "representativesVehicles.representatives.form.passwordTooShort",
  REPRESENTATIVE_COMPANY_PASSWORD_TOO_LONG:
    "representativesVehicles.representatives.form.passwordTooLong",
  REPRESENTATIVE_CURSOR_INVALID:
    "representativesVehicles.representatives.errors.cursorInvalid",
  REPRESENTATIVE_IDENTITY_INCONSISTENT:
    "representativesVehicles.representatives.errors.unavailable",
  REPRESENTATIVE_OPERATIONAL_COMPATIBILITY_MISSING:
    "representativesVehicles.representatives.errors.unavailable",
  REPRESENTATIVE_DEBT_LIMIT_INVALID:
    "representativesVehicles.representatives.form.debtInvalid",
  REPRESENTATIVE_DEBT_LIMIT_PRECISION_INVALID:
    "representativesVehicles.representatives.form.debtInvalid",
  REPRESENTATIVE_UPDATE_EMPTY:
    "representativesVehicles.representatives.form.noChanges",
  REPRESENTATIVE_UPDATE_FIELD_INVALID: "errors.codes.VALIDATION_ERROR",
  REPRESENTATIVE_REQUEST_ID_INVALID: "errors.codes.VALIDATION_ERROR",
  REPRESENTATIVE_SEARCH_INVALID:
    "representativesVehicles.representatives.searchHint",
};

export function representativeErrorMessage(
  error: unknown,
  fallback: string,
): string {
  const code = apiErrorCode(error);
  const key = code ? representativeErrorKeys[code] : undefined;
  return key ? i18n.t(key) : apiErrorMessage(error, fallback);
}
