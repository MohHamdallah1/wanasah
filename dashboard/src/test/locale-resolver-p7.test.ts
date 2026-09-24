import {
  readdirSync,
  readFileSync,
} from "node:fs";
import {
  join,
  resolve,
} from "node:path";
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

    it("keeps currentLocale delegated to the shared resolver", () => {
      const source =
        readFileSync(
          resolve(
            process.cwd(),
            "src/i18n/index.ts",
          ),
          "utf8",
        );

      expect(source).toContain(
        "resolveI18nLocale(i18n)",
      );
      expect(source).not.toContain(
        'i18n.language.startsWith("ar")',
      );
    });

    it("keeps production formatting behind the shared locale authority", () => {
      const sourceRoot = resolve(
        process.cwd(),
        "src",
      );
      const offenders: string[] = [];

      const visit = (
        directory: string,
      ) => {
        for (const entry of readdirSync(
          directory,
          {
            withFileTypes: true,
          },
        )) {
          const filePath = join(
            directory,
            entry.name,
          );

          if (entry.isDirectory()) {
            if (
              entry.name === "test"
            ) {
              continue;
            }
            visit(filePath);
            continue;
          }

          if (
            !/\.(ts|tsx)$/.test(
              entry.name,
            )
          ) {
            continue;
          }

          if (
            filePath.endsWith(
              join("lib", "locale.ts"),
            )
          ) {
            continue;
          }

          const source =
            readFileSync(
              filePath,
              "utf8",
            );
          const compact =
            source.replace(
              /\s+/g,
              " ",
            );

          const hardcodedIntl =
            /Intl\.(?:NumberFormat|DateTimeFormat)\(\s*["'][A-Za-z]{2}(?:-[A-Za-z0-9]{2,8})*["']/;
          const hardcodedLocaleMethod =
            /\.toLocale(?:String|DateString|TimeString)\(\s*["'][A-Za-z]{2}(?:-[A-Za-z0-9]{2,8})*["']/;
          const binaryArabicFallback =
            /i18n\.language\.startsWith\(\s*["']ar["']\s*\)/;
          const regionalLocaleLiteral =
            /["'](?:ar-JO|ar-EG|en-US)["']/;

          if (
            hardcodedIntl.test(
              compact,
            ) ||
            hardcodedLocaleMethod.test(
              compact,
            ) ||
            binaryArabicFallback.test(
              compact,
            ) ||
            regionalLocaleLiteral.test(
              compact,
            )
          ) {
            offenders.push(
              filePath,
            );
          }
        }
      };

      visit(sourceRoot);

      expect(
        offenders,
      ).toEqual([]);
    });
  },
);
