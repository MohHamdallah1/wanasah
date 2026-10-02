import {
  useRef,
  useState,
} from "react";

import {
  deriveExactMoneyPair,
} from "@/lib/exactMoney";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import type {
  PriceFieldError,
} from "@/pages/products/pricing/types";

export const compactEditableMoney = (
  value: string | null,
): string => {
  if (value === null) {
    return "";
  }

  const trimmed = value.trim();
  const match =
    /^(\d+)(?:\.(\d+))?$/.exec(
      trimmed,
    );

  if (!match) {
    return trimmed;
  }

  const whole = match[1];
  let fraction = match[2] ?? "";

  while (
    fraction.length > 3 &&
    fraction.endsWith("0")
  ) {
    fraction = fraction.slice(
      0,
      -1,
    );
  }

  fraction = fraction.padEnd(
    3,
    "0",
  );

  return fraction
    ? `${whole}.${fraction}`
    : whole;
};

export function usePriceEditState() {
  const [
    priceEdit,
    setPriceEdit,
  ] =
    useState<SimpleProduct | null>(
      null
    );
  const [
    editPackagePrice,
    setEditPackagePrice,
  ] = useState("");
  const [
    editUnitPrice,
    setEditUnitPrice,
  ] = useState("");
  const [
    priceFieldError,
    setPriceFieldError,
  ] = useState<PriceFieldError | null>(
    null
  );
  const editPackagePriceRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const editUnitPriceRef =
    useRef<HTMLInputElement | null>(
      null
    );

  const openPriceEditor = (
    product: SimpleProduct
  ) => {
    setPriceFieldError(null);
    setPriceEdit(product);
    setEditPackagePrice(
      compactEditableMoney(
        product.package_price,
      ),
    );
    setEditUnitPrice(
      compactEditableMoney(
        product.unit_price,
      ),
    );
  };

  const cancelPriceEdit =
    () => {
      setPriceEdit(null);
    };

  const updatePackagePrice = (
    value: string
  ) => {
    setEditPackagePrice(
      value
    );
    if (
      priceFieldError?.field ===
      "packagePrice"
    ) {
      setPriceFieldError(null);
    }
  };

  const updateUnitPrice = (
    value: string
  ) => {
    setEditUnitPrice(
      value
    );
    if (
      priceFieldError?.field ===
      "unitPrice"
    ) {
      setPriceFieldError(null);
    }
  };

  const editDerived =
    priceEdit
      ? deriveExactMoneyPair(
          Boolean(
            priceEdit.package_uom_code
          ),
          String(
            priceEdit.units_per_package
          ),
          editPackagePrice,
          editUnitPrice
        )
      : null;

  return {
    priceEdit,
    setPriceEdit,
    editPackagePrice,
    setEditPackagePrice,
    editUnitPrice,
    setEditUnitPrice,
    priceFieldError,
    setPriceFieldError,
    editPackagePriceRef,
    editUnitPriceRef,
    openPriceEditor,
    cancelPriceEdit,
    updatePackagePrice,
    updateUnitPrice,
    editDerived,
  };
}
