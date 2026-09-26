const LAST_COMPANY_CODE_KEY =
  "wanasah_last_company_code";

const PERSISTENT_LOCAL_STORAGE_PREFIXES =
  [
    "wanasah:products:display:v",
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
  (): void => {
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
  };
