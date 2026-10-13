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
    "representativesVehicles.representatives.form.passwordInvalid",
  REPRESENTATIVE_COMPANY_PASSWORD_TOO_LONG:
    "representativesVehicles.representatives.form.passwordInvalid",
};

export function representativeErrorMessage(
  error: unknown,
  fallback: string,
): string {
  const code = apiErrorCode(error);
  const key = code ? representativeErrorKeys[code] : undefined;
  return key ? i18n.t(key) : apiErrorMessage(error, fallback);
}
