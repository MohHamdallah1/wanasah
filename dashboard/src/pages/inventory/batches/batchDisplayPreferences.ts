export const BATCH_DISPLAY_PREFERENCES_VERSION = 1 as const;
export const DEFAULT_BATCH_EXPIRY_WARNING_DAYS = 30;
export const MAX_BATCH_EXPIRY_WARNING_DAYS = 3650;

export interface BatchDisplayPreferences {
  version: typeof BATCH_DISPLAY_PREFERENCES_VERSION;
  expiryWarningDays: number;
}

const positiveSafeInteger = (value: number): boolean =>
  Number.isSafeInteger(value) && value > 0;

const scopedKey = (companyId: number, principalId: number): string =>
  `wanasah:inventory:batches:display:v${BATCH_DISPLAY_PREFERENCES_VERSION}:${companyId}:${principalId}`;

const defaults = (): BatchDisplayPreferences => ({
  version: BATCH_DISPLAY_PREFERENCES_VERSION,
  expiryWarningDays: DEFAULT_BATCH_EXPIRY_WARNING_DAYS,
});

export const normalizeBatchExpiryWarningDays = (value: number): number => {
  if (!Number.isFinite(value)) return DEFAULT_BATCH_EXPIRY_WARNING_DAYS;
  return Math.min(
    MAX_BATCH_EXPIRY_WARNING_DAYS,
    Math.max(1, Math.trunc(value)),
  );
};

export const readBatchDisplayPreferences = (
  companyId: number,
  principalId: number,
): BatchDisplayPreferences => {
  if (!positiveSafeInteger(companyId) || !positiveSafeInteger(principalId)) {
    return defaults();
  }
  try {
    const raw = localStorage.getItem(scopedKey(companyId, principalId));
    if (!raw) return defaults();
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (
      parsed.version !== BATCH_DISPLAY_PREFERENCES_VERSION ||
      typeof parsed.expiryWarningDays !== "number" ||
      !Number.isSafeInteger(parsed.expiryWarningDays) ||
      parsed.expiryWarningDays < 1 ||
      parsed.expiryWarningDays > MAX_BATCH_EXPIRY_WARNING_DAYS
    ) {
      return defaults();
    }
    return {
      version: BATCH_DISPLAY_PREFERENCES_VERSION,
      expiryWarningDays: parsed.expiryWarningDays,
    };
  } catch {
    return defaults();
  }
};

export const writeBatchDisplayPreferences = (
  companyId: number,
  principalId: number,
  preferences: BatchDisplayPreferences,
): void => {
  if (!positiveSafeInteger(companyId) || !positiveSafeInteger(principalId)) return;
  try {
    localStorage.setItem(
      scopedKey(companyId, principalId),
      JSON.stringify({
        version: BATCH_DISPLAY_PREFERENCES_VERSION,
        expiryWarningDays: normalizeBatchExpiryWarningDays(
          preferences.expiryWarningDays,
        ),
      }),
    );
  } catch {
    // A display preference must never block the authoritative inventory read.
  }
};