const LAST_COMPANY_CODE_KEY =
  "wanasah_last_company_code";
const CANONICAL_BACKOFFICE_IDENTITY_MIGRATION_KEY =
  "wanasah:backoffice-identity:v1";

const PERSISTENT_LOCAL_STORAGE_PREFIXES =
  [
    "wanasah:products:display:v",
    "wanasah:layout:",
    "wanasah:backoffice-identity:",
  ] as const;

const LEGACY_BACKOFFICE_IDENTITY_PREFIXES = [
  "wanasah:durable:v1:",
  "wanasah:products:display:v",
  "wanasah:product-draft:",
  "wanasah:product-import:",
  "wanasah:supplier-draft:",
] as const;

export const readLastCompanyCode = (): string =>
  localStorage.getItem(
    LAST_COMPANY_CODE_KEY,
  )?.trim() ?? "";

export const rememberLastCompanyCode = (
  companyCode: string,
): void => {
  const normalized =
    companyCode.trim();
  if (!normalized) {
    localStorage.removeItem(
      LAST_COMPANY_CODE_KEY,
    );
    return;
  }
  localStorage.setItem(
    LAST_COMPANY_CODE_KEY,
    normalized,
  );
};

export const migrateLegacyBackofficeIdentityStorage = (): void => {
  if (
    localStorage.getItem(
      CANONICAL_BACKOFFICE_IDENTITY_MIGRATION_KEY,
    ) === "done"
  ) {
    return;
  }

  const staleKeys = Array.from(
    { length: localStorage.length },
    (_, index) => localStorage.key(index),
  ).filter(
    (key): key is string =>
      key !== null &&
      LEGACY_BACKOFFICE_IDENTITY_PREFIXES.some(
        (prefix) => key.startsWith(prefix),
      ),
  );

  for (const key of staleKeys) {
    localStorage.removeItem(key);
  }
  localStorage.removeItem("driver_id");
  localStorage.setItem(
    CANONICAL_BACKOFFICE_IDENTITY_MIGRATION_KEY,
    "done",
  );
};

// A login generation fences asynchronous work, including same-principal re-login.
// This is client response admission only; the server still authorizes every bearer.
const SESSION_GENERATION_KEY = "wanasah:auth-session:generation";
export const beginDashboardSession = (): void => {
  localStorage.setItem(SESSION_GENERATION_KEY, crypto.randomUUID());
};

export type DashboardSession = { generation: string; identity: string };
const dashboardIdentity = (): string => JSON.stringify([
  localStorage.getItem("company_id"),
  localStorage.getItem("principal_id"),
  localStorage.getItem("backoffice_user_id"),
  readRefreshIdentity(localStorage.getItem("refresh_token") || ""),
]);

export const captureDashboardSession = (): DashboardSession => {
  if (!localStorage.getItem(SESSION_GENERATION_KEY)) beginDashboardSession();
  return {
    generation: localStorage.getItem(SESSION_GENERATION_KEY)!,
    identity: dashboardIdentity(),
  };
};

export const isDashboardSessionCurrent = (session: DashboardSession): boolean =>
  localStorage.getItem(SESSION_GENERATION_KEY) === session.generation &&
  dashboardIdentity() === session.identity;

export const invalidateDashboardSession = (): void => {
  localStorage.removeItem(SESSION_GENERATION_KEY);
};

type RefreshIdentity = {
  sub: string;
  companyId: string;
};

const readRefreshIdentity = (
  token: string,
): RefreshIdentity | null => {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) {
      return null;
    }

    const base64Url = parts[1]
      .replace(/-/g, "+")
      .replace(/_/g, "/");
    const padded = base64Url.padEnd(
      base64Url.length +
        ((4 - (base64Url.length % 4)) % 4),
      "=",
    );
    const payload: unknown = JSON.parse(
      atob(padded),
    );

    if (
      typeof payload !== "object" ||
      payload === null ||
      !("type" in payload) ||
      !("sub" in payload) ||
      !("company_id" in payload)
    ) {
      return null;
    }

    const claims = payload as {
      type: unknown;
      sub: unknown;
      company_id: unknown;
    };
    if (
      claims.type !== "refresh" ||
      (typeof claims.sub !== "string" &&
        typeof claims.sub !== "number") ||
      (typeof claims.company_id !== "string" &&
        typeof claims.company_id !== "number")
    ) {
      return null;
    }

    return {
      sub: String(claims.sub),
      companyId: String(claims.company_id),
    };
  } catch {
    return null;
  }
};

export const readAccessTokenIfRefreshAdvanced = (
  attemptedRefreshToken: string,
): string | null => {
  const currentRefresh =
    localStorage.getItem("refresh_token");
  const currentAccess =
    localStorage.getItem("admin_token");

  if (
    !currentRefresh ||
    !currentAccess ||
    currentRefresh === attemptedRefreshToken
  ) {
    return null;
  }

  const attemptedIdentity =
    readRefreshIdentity(attemptedRefreshToken);
  const currentIdentity =
    readRefreshIdentity(currentRefresh);

  if (
    !attemptedIdentity ||
    !currentIdentity ||
    attemptedIdentity.sub !==
      currentIdentity.sub ||
    attemptedIdentity.companyId !==
      currentIdentity.companyId
  ) {
    return null;
  }

  return currentAccess;
};

export const clearLocalStoragePreservingLoginHintsAndPreferences =
  (expectedSession?: DashboardSession): boolean => {
    if (expectedSession && !isDashboardSessionCurrent(expectedSession)) return false;
    const lastCompanyCode =
      readLastCompanyCode();

    const persistentEntries =
      Array.from(
        {
          length:
            localStorage.length,
        },
        (_, index) => {
          const key =
            localStorage.key(index);
          if (
            !key ||
            !PERSISTENT_LOCAL_STORAGE_PREFIXES.some(
              (prefix) =>
                key.startsWith(prefix),
            )
          ) {
            return null;
          }

          const value =
            localStorage.getItem(key);
          return value === null
            ? null
            : ([key, value] as const);
        },
      ).filter(
        (
          entry,
        ): entry is readonly [
          string,
          string,
        ] => entry !== null,
      );

    localStorage.clear();

    if (lastCompanyCode) {
      localStorage.setItem(
        LAST_COMPANY_CODE_KEY,
        lastCompanyCode,
      );
    }

    for (const [
      key,
      value,
    ] of persistentEntries) {
      localStorage.setItem(
        key,
        value,
      );
    }
    return true;
  };
