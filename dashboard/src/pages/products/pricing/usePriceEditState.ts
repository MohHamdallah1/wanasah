import {
  useRef,
  useState,
} from "react";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import type {
  PriceFieldError,
} from "@/pages/products/pricing/types";

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
  };
}
