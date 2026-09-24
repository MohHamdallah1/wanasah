export const DEFAULT_APP_LOCALE =
  "en-US";

const DEFAULT_LANGUAGE_LOCALES:
  Readonly<Record<string, string>> = {
    ar: "ar-JO",
    en: "en-US",
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

    // Only bare languages get the app's
    // preferred regional default. Explicit
    // user/resource locales such as ar-EG,
    // en-GB, fr-FR or de-DE are preserved.
    if (
      canonical.toLowerCase() ===
      baseLanguage
    ) {
      return (
        DEFAULT_LANGUAGE_LOCALES[
          baseLanguage
        ] ?? canonical
      );
    }

    return canonical;
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
