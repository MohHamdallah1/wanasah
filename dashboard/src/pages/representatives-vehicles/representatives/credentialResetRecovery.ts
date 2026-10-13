import { apiErrorCode, apiErrorStatus } from "@/lib/apiErrors";

export type CredentialResetAttempt = {
  storageKey: string;
  requestId: string;
  recovered: boolean;
};

export class CredentialResetRecoveryUnavailable extends Error {}

const prefix = "wanasah:representative-credential-reset:v1";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const withRecoveryStorage = <T,>(operation: () => T): T => {
  try {
    return operation();
  } catch {
    throw new CredentialResetRecoveryUnavailable();
  }
};

const storageKey = (representativeId: number): string => {
  const company = localStorage.getItem("company_id");
  const principal = localStorage.getItem("principal_id");
  if (
    !company || !principal ||
    !/^[1-9]\d*$/.test(company) || !/^[1-9]\d*$/.test(principal) ||
    !Number.isSafeInteger(Number(company)) || !Number.isSafeInteger(Number(principal)) ||
    !Number.isSafeInteger(representativeId) || representativeId <= 0
  ) {
    throw new CredentialResetRecoveryUnavailable();
  }
  return `${prefix}:${company}:${principal}:${representativeId}`;
};

const readRequestId = (key: string): string | null => {
  const value = sessionStorage.getItem(key);
  if (value !== null && !uuid.test(value)) {
    throw new CredentialResetRecoveryUnavailable();
  }
  return value;
};

export const hasCredentialResetRecovery = (representativeId: number): boolean =>
  withRecoveryStorage(() => readRequestId(storageKey(representativeId)) !== null);

// The API deliberately accepts no password or payload. Only an opaque UUID is
// stored, and the key partitions it by mutation family, company, principal and target.
export const prepareCredentialReset = (representativeId: number): CredentialResetAttempt =>
  withRecoveryStorage(() => {
    const key = storageKey(representativeId);
    const existing = readRequestId(key);
    if (existing) return { storageKey: key, requestId: existing, recovered: true };
    const requestId = crypto.randomUUID();
    sessionStorage.setItem(key, requestId);
    return { storageKey: key, requestId, recovered: false };
  });

export const clearCredentialResetRecovery = (attempt: CredentialResetAttempt): void =>
  withRecoveryStorage(() => {
    if (readRequestId(attempt.storageKey) === attempt.requestId) {
      sessionStorage.removeItem(attempt.storageKey);
    }
  });

export const startNewCredentialReset = (representativeId: number): void =>
  withRecoveryStorage(() => sessionStorage.removeItem(storageKey(representativeId)));

export const resetValidationProvesNoExecution = (error: unknown): boolean =>
  apiErrorStatus(error) === 422 && [
    "VALIDATION_ERROR",
    "REPRESENTATIVE_COMPANY_PASSWORD_INVALID",
    "REPRESENTATIVE_COMPANY_PASSWORD_TOO_SHORT",
    "REPRESENTATIVE_COMPANY_PASSWORD_TOO_LONG",
  ].includes(apiErrorCode(error) ?? "");
