import type { TFunction } from "i18next";

import {
  absoluteQuantity,
  compareQuantity,
  formatCommercialQuantity,
  formatQuantity,
} from "@/lib/quantity";
import type { LedgerEntry } from "./contracts";
import { ledgerStatusLabel, ledgerText } from "./ledgerI18n";

export const ledgerSignedQuantity = (
  entry: LedgerEntry,
  unitLabel: (code: string) => string,
): string => {
  const sign = compareQuantity(entry.quantity, "0") < 0 ? "-" : "+";
  if (entry.input_quantity && entry.input_uom_code) {
    return `${sign}${formatQuantity(entry.input_quantity, unitLabel(entry.input_uom_code))}`;
  }
  const display = formatCommercialQuantity(
    absoluteQuantity(entry.quantity),
    unitLabel(entry.display_uom_code),
    unitLabel(entry.base_uom_code),
    entry.display_factor_to_base,
  );
  return `${sign}${display.primary}`;
};

export const ledgerBalance = (
  entry: LedgerEntry,
  value: LedgerEntry["balance_before"],
  unitLabel: (code: string) => string,
): string => {
  if (value === null) return "—";
  return formatCommercialQuantity(
    value,
    unitLabel(entry.display_uom_code),
    unitLabel(entry.base_uom_code),
    entry.display_factor_to_base,
  ).primary;
};

export const ledgerMoney = (value: string | null, currency: string): string =>
  value ? `${value} ${currency}` : "—";

export const ledgerLocationEvidence = (
  t: TFunction,
  language: string,
  entry: LedgerEntry,
): { source: string; destination: string } => {
  const text = (key: Parameters<typeof ledgerText>[2]) => ledgerText(t, language, key);
  const location = (name: string | null, id: number | null) =>
    name ?? (id !== null ? `#${new Intl.NumberFormat("en-US", { useGrouping: false }).format(id)}` : text("external"));
  const withEvidence = (name: string, kind: string | null | undefined, status: string | null) => {
    const locationKind = kind === "WAREHOUSE" ? text("locationWarehouse")
      : kind === "VEHICLE" ? text("locationVehicle")
      : kind === "IN_TRANSIT" ? text("locationTransit") : null;
    const statusLabel = ledgerStatusLabel(t, language, status);
    return [locationKind, name, statusLabel].filter(Boolean).join(" · ");
  };
  return {
    source: withEvidence(location(entry.source_location_name, entry.source_location_id),
      entry.source_location_type, entry.source_stock_status),
    destination: withEvidence(location(entry.destination_location_name, entry.destination_location_id),
      entry.destination_location_type, entry.destination_stock_status),
  };
};

export const ledgerQuantityMeaning = (
  t: TFunction, language: string, entry: LedgerEntry,
): string => ledgerText(t, language,
  entry.movement_kind === "RESERVATION" ? "reservationChange"
    : entry.movement_kind === "STATUS_CHANGE" ? "statusChange" : "physicalChange");
