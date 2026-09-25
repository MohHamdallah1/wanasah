import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import {
  deriveExactMoneyPair,
} from "../lib/exactMoney";

const readSource = (
  relativePath: string,
): string =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe(
  "Products exact money preview",
  () => {
    it("derives package price without floating-point drift", () => {
      expect(
        deriveExactMoneyPair(
          true,
          "3",
          "",
          "0.1",
        ),
      ).toEqual({
        packagePrice: "0.300000",
        unitPrice: "0.100000",
        independent: false,
      });
    });

    it("matches backend HALF_UP division at six decimals", () => {
      expect(
        deriveExactMoneyPair(
          true,
          "2",
          "1.000001",
          "",
        ),
      ).toEqual({
        packagePrice: "1.000001",
        unitPrice: "0.500001",
        independent: false,
      });

      expect(
        deriveExactMoneyPair(
          true,
          "3",
          "1",
          "",
        ),
      ).toEqual({
        packagePrice: "1.000000",
        unitPrice: "0.333333",
        independent: false,
      });
    });

    it("quantizes supplied money before deriving the missing side", () => {
      expect(
        deriveExactMoneyPair(
          true,
          "3",
          "",
          "0.1234565",
        ),
      ).toEqual({
        packagePrice: "0.370371",
        unitPrice: "0.123457",
        independent: false,
      });
    });

    it("preserves independent exact prices without deriving either side", () => {
      expect(
        deriveExactMoneyPair(
          true,
          "50",
          "10.000000",
          "0.250000",
        ),
      ).toEqual({
        packagePrice: "10.000000",
        unitPrice: "0.250000",
        independent: true,
      });
    });

    it("keeps no-package unit prices exact", () => {
      expect(
        deriveExactMoneyPair(
          false,
          "1",
          "",
          "99999999999999.999999",
        ),
      ).toEqual({
        packagePrice: null,
        unitPrice:
          "99999999999999.999999",
        independent: false,
      });
    });

    it("rejects zero-after-rounding, invalid, and overflow values", () => {
      expect(
        deriveExactMoneyPair(
          false,
          "1",
          "",
          "0.0000004",
        ),
      ).toBeNull();
      expect(
        deriveExactMoneyPair(
          true,
          "2",
          "",
          "99999999999999.999999",
        ),
      ).toBeNull();
      expect(
        deriveExactMoneyPair(
          true,
          "3",
          "not-money",
          "",
        ),
      ).toBeNull();
    });

    it("keeps package quantity as bounded integer authority, not money", () => {
      expect(
        deriveExactMoneyPair(
          true,
          "1.5",
          "1",
          "",
        ),
      ).toBeNull();
      expect(
        deriveExactMoneyPair(
          true,
          "1000001",
          "1",
          "",
        ),
      ).toBeNull();
    });

    it("keeps product money paths string/exact and backend-authoritative", () => {
      const products = readSource(
        "../pages/products/ProductsPage.tsx",
      );
      const pricing = readSource(
        "../pages/PricingDashboard.tsx",
      );
      const localeNumbers = readSource(
        "../lib/localeNumbers.ts",
      );

      expect(products).toContain(
        "deriveExactMoneyPair(",
      );
      expect(products).not.toContain(
        "const derivedPrices =",
      );
      expect(products).not.toContain(
        "Number(unitRaw)",
      );
      expect(products).not.toContain(
        "Number(packageRaw)",
      );
      expect(products).toContain(
        "package_price.trim()",
      );
      expect(products).toContain(
        "unit_price.trim()",
      );

      expect(pricing).toContain(
        "amount: entryForm.amount.trim()",
      );
      expect(pricing).not.toContain(
        "parseFloat(",
      );
      expect(pricing).not.toContain(
        "toFixed(",
      );

      expect(localeNumbers).toContain(
        "BigInt(match[2])",
      );
      expect(localeNumbers).not.toContain(
        "Number(value)",
      );
    });
  },
);
