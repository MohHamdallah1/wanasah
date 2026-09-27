import type {
  TFunction,
} from "i18next";

import {
  parseProductImportErrorPage,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type I18nLookup = {
  exists: (key: string) => boolean;
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
      const XLSX =
        await import("xlsx");

      const headers = [
        t(
          "products.fields.name"
        ),
        t(
          "products.fields.family"
        ),
        t(
          "products.fields.packageUom"
        ),
        t(
          "products.fields.unitsPerPackage"
        ),
        t(
          "products.fields.packagePrice"
        ),
        t(
          "products.fields.unitPrice"
        ),
        t(
          "products.fields.unitBarcode"
        ),
        t(
          "products.fields.packageBarcode"
        ),
        t(
          "products.fields.lotControlMode"
        ),
        t(
          "products.fields.expiryControlMode"
        ),
      ];

      // Untouched template is intentionally headers-only.
      // Guidance and examples live in the UI so a user cannot
      // accidentally import a sample Product from the template.
      const productsSheet =
        XLSX.utils.aoa_to_sheet([
          headers,
        ]);
      productsSheet["!cols"] =
        headers.map(() => ({
          wch: 24,
        }));
      productsSheet[
        "!autofilter"
      ] = {
        ref:
          XLSX.utils.encode_range({
            s: {
              r: 0,
              c: 0,
            },
            e: {
              r: 0,
              c:
                headers.length -
                1,
            },
          }),
      };

      const workbook =
        XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(
        workbook,
        productsSheet,
        t(
          "products.importTemplateProductsSheet"
        ).slice(0, 31)
      );

      XLSX.writeFile(
        workbook,
        "products-import-template.xlsx",
        {
          compression: true,
        }
      );
    };


  return {
    downloadErrorReport,
    downloadTemplate,
  };
}
