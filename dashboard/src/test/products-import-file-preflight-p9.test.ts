import {
  describe,
  expect,
  it,
} from "vitest";
import * as XLSX from "xlsx";

import {
  productImportFileHasDataRows,
} from "@/pages/products/import/productImportFilePreflight";

describe(
  "Product import file preflight",
  () => {
    it("rejects a headers-only CSV and accepts one product row", async () => {
      const emptyFile =
        new File(
          [
            "Product name,Unit price\n",
          ],
          "products.csv",
          {
            type: "text/csv",
          }
        );
      const dataFile =
        new File(
          [
            "Product name,Unit price\nCoffee,2.50\n",
          ],
          "products.csv",
          {
            type: "text/csv",
          }
        );

      await expect(
        productImportFileHasDataRows(
          emptyFile
        )
      ).resolves.toBe(false);
      await expect(
        productImportFileHasDataRows(
          dataFile
        )
      ).resolves.toBe(true);
    });

    it("rejects a headers-only XLSX and accepts one product row", async () => {
      const makeFile = (
        rows: unknown[][],
      ) => {
        const workbook =
          XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(
          workbook,
          XLSX.utils.aoa_to_sheet(
            rows
          ),
          "Products"
        );
        const bytes =
          XLSX.write(
            workbook,
            {
              type: "array",
              bookType: "xlsx",
            }
          );
        return new File(
          [bytes],
          "products.xlsx",
          {
            type:
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          }
        );
      };

      await expect(
        productImportFileHasDataRows(
          makeFile([
            [
              "Product name",
              "Unit price",
            ],
          ])
        )
      ).resolves.toBe(false);

      await expect(
        productImportFileHasDataRows(
          makeFile([
            [
              "Product name",
              "Unit price",
            ],
            [
              "Coffee",
              2.5,
            ],
          ])
        )
      ).resolves.toBe(true);
    });
  },
);
