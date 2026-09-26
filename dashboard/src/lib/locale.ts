export const DEFAULT_APP_LOCALE =
  "en-US";

const DEFAULT_LANGUAGE_LOCALES:
  Readonly<Record<string, string>> = {
    ar: "ar-JO",
    en: "en-US",
  };

const applyAppNumberingSystem = (
  locale: string,
): string => {
  try {
    const parsed =
      new Intl.Locale(locale);

    if (
      parsed.language.toLowerCase() !==
      "ar"
    ) {
      return parsed.toString();
    }

    return new Intl.Locale(
      parsed,
      {
        numberingSystem: "latn",
      },
    ).toString();
  } catch {
    return locale;
  }
};

export type I18nLocaleSource = {
  resolvedLanguage?:
    | string
    | null;
  language?:
    | string
    | null;
};

export const resolveAppLocale = (
  language:
    | string
    | null
    | undefined,
): string => {
  const normalized = (
    language ?? ""
  )
    .trim()
    .replace(/_/g, "-");

  if (!normalized) {
    return DEFAULT_APP_LOCALE;
  }

  try {
    const canonical =
      Intl.getCanonicalLocales(
        normalized,
      )[0];

    if (!canonical) {
      return DEFAULT_APP_LOCALE;
    }

    const baseLanguage =
      canonical
        .split("-")[0]
        .toLowerCase();

    const regionalLocale =
      canonical.toLowerCase() ===
      baseLanguage
        ? (
            DEFAULT_LANGUAGE_LOCALES[
              baseLanguage
            ] ?? canonical
          )
        : canonical;

    return applyAppNumberingSystem(
      regionalLocale,
    );
  } catch {
    return DEFAULT_APP_LOCALE;
  }
};

export const resolveI18nLocale = (
  source: I18nLocaleSource,
): string =>
  resolveAppLocale(
    source.resolvedLanguage ||
      source.language,
  );
