import {
  describe,
  expect,
  it,
} from "vitest";
import * as XLSX from "xlsx";

import {
  productImportFileHasDataRows,
} from "@/pages/products/import/productImportFilePreflight";

function workbookFile(workbook: XLSX.WorkBook): File {
  return new File(
    [XLSX.write(workbook, { type: "array", bookType: "xlsx" })],
    "products.xlsx",
    { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
  );
}

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

    it("follows official template metadata even when its hidden sheet comes first", async () => {
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(workbook,
        XLSX.utils.aoa_to_sheet([
          ["WANASAH_PRODUCT_IMPORT_V1"], ["المنتجات"],
        ]), "_wanasah_meta");
      XLSX.utils.book_append_sheet(workbook,
        XLSX.utils.aoa_to_sheet([["اسم المنتج"], ["قهوة"]]),
        "المنتجات");
      workbook.Workbook = { Sheets: [
        { name: "_wanasah_meta", Hidden: 1 },
        { name: "المنتجات", Hidden: 0 },
      ] };
      await expect(productImportFileHasDataRows(workbookFile(workbook)))
        .resolves.toBe(true);
    });

    it("uses the sole visible external sheet, not the first hidden sheet", async () => {
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(workbook,
        XLSX.utils.aoa_to_sheet([["Internal settings"]]), "Internal");
      XLSX.utils.book_append_sheet(workbook,
        XLSX.utils.aoa_to_sheet([["Product name"], ["Coffee"]]),
        "Products");
      workbook.Workbook = { Sheets: [
        { name: "Internal", Hidden: 1 },
        { name: "Products", Hidden: 0 },
      ] };
      await expect(productImportFileHasDataRows(workbookFile(workbook)))
        .resolves.toBe(true);
    });

    it("defers ambiguous external sheets and invalid metadata to the backend", async () => {
      const external = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(external,
        XLSX.utils.aoa_to_sheet([["Product name"]]), "Cover");
      XLSX.utils.book_append_sheet(external,
        XLSX.utils.aoa_to_sheet([["Product name"], ["Coffee"]]),
        "Products");
      await expect(productImportFileHasDataRows(workbookFile(external)))
        .resolves.toBe(null);

      const invalidTemplate = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(invalidTemplate,
        XLSX.utils.aoa_to_sheet([["WRONG_MARKER"], ["Products"]]),
        "_wanasah_meta");
      XLSX.utils.book_append_sheet(invalidTemplate,
        XLSX.utils.aoa_to_sheet([["Product name"], ["Coffee"]]),
        "Products");
      await expect(productImportFileHasDataRows(workbookFile(invalidTemplate)))
        .resolves.toBe(null);
    });

    it("uses the reviewed patched SheetJS build for untrusted workbook parsing", () => {
      // The legacy npm registry stops at vulnerable xlsx@0.18.5.
      // The lockfile pins this reviewed upstream CDN build and its integrity hash.
      expect(XLSX.version).toBe("0.20.3");
    });

    it("fails closed on a synthetic truncated ZIP workbook instead of treating it as product rows", async () => {
      const malformed = new File(
        [new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0])],
        "products.xlsx",
        { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      );

      await expect(productImportFileHasDataRows(malformed))
        .resolves.toBe(null);
    });

    it("keeps canonical cells intact when synthetic SpreadsheetML contains suspicious attributes", () => {
      // This is a bounded malicious-attribute compatibility probe, not a claim
      // to reproduce either historical advisory exploit.
      const xml = [
        '<?xml version="1.0"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        '<Worksheet ss:Name="Products" __proto__="wanasahPoisoned" constructor="wanasahPoisoned">',
        '<Table><Row><Cell><Data ss:Type="String">Product name</Data></Cell>',
        '<Cell><Data ss:Type="String">Unit price</Data></Cell></Row>',
        '<Row><Cell><Data ss:Type="String">Coffee</Data></Cell>',
        '<Cell><Data ss:Type="Number">2.5</Data></Cell></Row></Table>',
        '</Worksheet></Workbook>',
      ].join("");
      const before = Object.prototype.hasOwnProperty.call(Object.prototype, "wanasahPoisoned");
      expect(before).toBe(false);

      const parsed = XLSX.read(xml, { type: "string" });
      expect(parsed.SheetNames).toEqual(["Products"]);
      expect(XLSX.utils.sheet_to_json(parsed.Sheets.Products, { header: 1 }))
        .toEqual([["Product name", "Unit price"], ["Coffee", 2.5]]);
      expect(Object.prototype.hasOwnProperty.call(Object.prototype, "wanasahPoisoned")).toBe(false);
    });
  },
);
