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
