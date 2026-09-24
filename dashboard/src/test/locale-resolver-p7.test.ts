import {
  describe,
  expect,
  it,
} from "vitest";

import {
  DEFAULT_APP_LOCALE,
  resolveAppLocale,
  resolveI18nLocale,
} from "@/lib/locale";

describe(
  "shared dashboard locale resolver",
  () => {
    it("uses app regional defaults for bare Arabic and English", () => {
      expect(
        resolveAppLocale("ar"),
      ).toBe("ar-JO");
      expect(
        resolveAppLocale("en"),
      ).toBe("en-US");
    });

    it("preserves explicit regional locales", () => {
      expect(
        resolveAppLocale("ar-EG"),
      ).toBe("ar-EG");
      expect(
        resolveAppLocale("en-GB"),
      ).toBe("en-GB");
      expect(
        resolveAppLocale("fr-FR"),
      ).toBe("fr-FR");
    });

    it("keeps future bare languages in their own locale instead of falling back to English", () => {
      expect(
        resolveAppLocale("fr"),
      ).toBe("fr");
      expect(
        resolveAppLocale("de"),
      ).toBe("de");
    });

    it("canonicalizes underscore locale input", () => {
      expect(
        resolveAppLocale("pt_BR"),
      ).toBe("pt-BR");
    });

    it("prefers i18next resolvedLanguage when available", () => {
      expect(
        resolveI18nLocale({
          resolvedLanguage:
            "fr-CA",
          language: "ar",
        }),
      ).toBe("fr-CA");
    });

    it("fails safely for missing or invalid locale input", () => {
      expect(
        resolveAppLocale(""),
      ).toBe(DEFAULT_APP_LOCALE);
      expect(
        resolveAppLocale(
          "not_a_real_locale_@@",
        ),
      ).toBe(DEFAULT_APP_LOCALE);
    });
  },
);
