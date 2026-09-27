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

      // Import sheet intentionally contains headers only.
      // Examples live on the guide sheet so the untouched template
      // can never create a fake/sample product.
      const productsSheet =
        XLSX.utils.aoa_to_sheet([
          headers,
        ]);
      productsSheet["!cols"] =
        headers.map(() => ({
          wch: 24,
        }));

      const guideRows = [
        [
          t(
            "products.importTemplateGuideTitle"
          ),
        ],
        [
          t(
            "products.importTemplateGuideTracking",
            {
              none: t(
                "products.tracking.importValues.NONE"
              ),
              optional: t(
                "products.tracking.importValues.OPTIONAL"
              ),
              required: t(
                "products.tracking.importValues.REQUIRED"
              ),
            }
          ),
        ],
        [
          t(
            "products.importTemplateGuidePackages"
          ),
        ],
        [
          t(
            "products.importTemplateGuidePrices"
          ),
        ],
        [],
        [
          t(
            "products.importTemplateExampleTitle"
          ),
        ],
        headers,
        [
          t(
            "products.importTemplateSampleName"
          ),
          t(
            "products.importTemplateSampleFamily"
          ),
          "CARTON",
          "50",
          "10.000",
          "",
          "6251234567890",
          "",
          t(
            "products.tracking.importValues.REQUIRED"
          ),
          t(
            "products.tracking.importValues.REQUIRED"
          ),
        ],
      ];
      const guideSheet =
        XLSX.utils.aoa_to_sheet(
          guideRows
        );
      guideSheet["!cols"] =
        headers.map(() => ({
          wch: 24,
        }));

      const workbook =
        XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(
        workbook,
        productsSheet,
        t(
          "products.importTemplateProductsSheet"
        ).slice(0, 31)
      );
      XLSX.utils.book_append_sheet(
        workbook,
        guideSheet,
        t(
          "products.importTemplateGuideSheet"
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
