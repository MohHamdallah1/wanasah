const LAST_COMPANY_CODE_KEY =
  "wanasah_last_company_code";

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

export const clearLocalStoragePreservingLastCompanyCode =
  (): void => {
    const lastCompanyCode =
      readLastCompanyCode();
    localStorage.clear();
    if (lastCompanyCode) {
      localStorage.setItem(
        LAST_COMPANY_CODE_KEY,
        lastCompanyCode,
      );
    }
  };
