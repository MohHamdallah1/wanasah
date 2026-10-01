import type {
  TFunction,
} from "i18next";

import {
  parseProductImportErrorPage,
} from "@/pages/products/contracts";
import { resolveI18nLocale } from "@/lib/locale";
import { saveImportFileArtifact } from "@/pages/products/import/productImportFileDownload";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type I18nLookup = {
  exists: (key: string) => boolean;
  language: string;
  resolvedLanguage?: string;
};

type Params = {
  importJobId: string | null;
  authFetch: AuthFetch;
  t: TFunction;
  i18n: I18nLookup;
};

export function createImportDownloads({
  importJobId,
  authFetch,
  t,
  i18n,
}: Params) {
  const csvCell = (
    value: string | number
  ) => {
    const text = String(value);
    return `"${text.replace(
      /"/g,
      '""'
    )}"`;
  };

  const downloadErrorReport =
    async () => {
      if (!importJobId) {
        return;
      }

      const allRows: Array<{
        row_number: number;
        code: string | null;
        message: string | null;
      }> = [];
      let afterRow = 0;

      while (true) {
        const result =
          parseProductImportErrorPage(
            await authFetch(
              `/simple-products/imports/${importJobId}/errors?after_row=${afterRow}&limit=1000`
            )
          );

        allRows.push(
          ...result.items
        );
        if (
          result.next_after_row ===
          null
        ) {
          break;
        }
        afterRow =
          result.next_after_row;
      }

      const lines = [
        [
          t(
            "products.errorReportRow"
          ),
          t(
            "products.errorReportCode"
          ),
          t(
            "products.errorReportMessage"
          ),
        ]
          .map(csvCell)
          .join(","),
        ...allRows.map(
          (row) => {
            const key = row.code
              ? `errors.codes.${row.code}`
              : "";
            const message =
              key &&
              i18n.exists(key)
                ? t(key)
                : t(
                    "network.serverError"
                  );
            return [
              row.row_number,
              row.code || "",
              message,
            ]
              .map(csvCell)
              .join(",");
          }
        ),
      ];

      const blob = new Blob(
        [
          "\ufeff",
          lines.join("\n"),
        ],
        {
          type: "text/csv;charset=utf-8",
        }
      );
      const href =
        URL.createObjectURL(
          blob
        );
      const link =
        document.createElement(
          "a"
        );
      link.href = href;
      link.download =
        "product-import-errors.csv";
      link.click();
      URL.revokeObjectURL(
        href
      );
    };

  const downloadTemplate =
    async () => {
      const locale = resolveI18nLocale(i18n);
      const raw =
        await authFetch(
          `/simple-products/import-template?locale=${encodeURIComponent(locale)}`
        );

      saveImportFileArtifact(
        raw,
        "INVALID_IMPORT_TEMPLATE_RESPONSE",
      );
    };


  const downloadCorrection =
    async () => {
      if (!importJobId) return;
      const locale = resolveI18nLocale(i18n);
      const raw = await authFetch(
        `/simple-products/imports/${importJobId}/correction?format=xlsx&locale=${encodeURIComponent(locale)}`,
      );
      saveImportFileArtifact(
        raw,
        "INVALID_IMPORT_CORRECTION_DOWNLOAD_RESPONSE",
        true,
      );
    };

  return {
    downloadErrorReport,
    downloadTemplate,
    downloadCorrection,
  };
}
