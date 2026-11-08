import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";

import { LedgerFilters } from "@/pages/inventory/ledger/LedgerFilters";
import { ledgerMovementFilterTypes } from "@/pages/inventory/ledger/ledgerMovementCatalog";
import { ledgerMovementLabel } from "@/pages/inventory/ledger/ledgerI18n";
import { LEDGER_OPERATION_REFERENCE_TYPES } from "@/pages/inventory/ledger/operationI18n";
import { buildLedgerCursorUrl } from "@/pages/inventory/ledger/buildLedgerCursorUrl";
import { buildLedgerOperationUrl } from "@/pages/inventory/ledger/operationContracts";

const t = ((_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key) as TFunction;

function filters(language: string, availableTypes: string[], filterType = "ALL", onChange = vi.fn()) {
  return <LedgerFilters t={t} language={language} search="" onSearchChange={vi.fn()}
    filterType={filterType} totalCount={null} onFilterTypeChange={onChange}
    availableTypes={availableTypes} loading={false} onRefresh={vi.fn()} />;
}

describe("#824 ledger reference-type filter parity", () => {
  it.each(["ar", "en"])("offers ALL plus every canonical type even if no first-page movement exists (%s)", (language) => {
    const { rerender } = render(filters(language, ["TRANSFER_RECEIPT"]));
    const select = screen.getByRole("combobox");
    const canonical = [...LEDGER_OPERATION_REFERENCE_TYPES];
    expect(canonical).toHaveLength(37);
    expect(Array.from(select.querySelectorAll("option"), option => option.value))
      .toEqual(["ALL", ...canonical]);
    expect(select.querySelectorAll("option")).toHaveLength(38);
    // Operations and Detailed can report different first-page types; neither
    // may constrain the filter catalog to that page or an observed warehouse.
    rerender(filters(language, ["DISPATCH_LOAD"]));
    expect(Array.from(select.querySelectorAll("option"), option => option.value))
      .toEqual(["ALL", ...canonical]);
    const labels = Array.from(select.querySelectorAll("option"), option => option.textContent);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("honors new server-reported types without duplicating canonical values or importing old-warehouse types", () => {
    const { rerender } = render(filters("en", ["TRANSFER", "FUTURE_STOCK_EVENT", "FUTURE_STOCK_EVENT"]));
    expect(screen.getByRole("option", { name: "FUTURE_STOCK_EVENT" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Transfer" })).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "FUTURE_STOCK_EVENT" })).toHaveLength(1);
    rerender(filters("en", ["TRANSFER_RECEIPT"]));
    expect(screen.queryByRole("option", { name: "FUTURE_STOCK_EVENT" })).not.toBeInTheDocument();
    // A selected historic type remains visible while the other mode fetches.
    rerender(filters("en", [], "FUTURE_STOCK_EVENT"));
    expect(screen.getByRole("combobox")).toHaveValue("FUTURE_STOCK_EVENT");
    expect(ledgerMovementFilterTypes(["\u0000BAD", "", "ALL", "TRANSFER", "TRANSFER"], "ALL"))
      .toEqual([...LEDGER_OPERATION_REFERENCE_TYPES]);
  });

  it.each(["ar", "en"])("keeps the two stocktake adjustment types distinct and describes empty categories (%s)", language => {
    const { container } = render(filters(language, [], "AUDIT_ADJUSTMENT"));
    const title = screen.getByRole("combobox").getAttribute("title") ?? "";
    expect(title.length).toBeGreaterThan(20);
    const options = Array.from(container.querySelectorAll("option"));
    const old = options.find(item => item.value === "STOCKTAKE_ADJUSTMENT")?.textContent;
    const current = options.find(item => item.value === "AUDIT_ADJUSTMENT")?.textContent;
    expect(old).not.toBe(current);
    expect(old).not.toBe(ledgerMovementLabel(t, language, "AUDIT_ADJUSTMENT"));
    expect(screen.getByRole("combobox")).toHaveValue("AUDIT_ADJUSTMENT");
  });

  it("preserves ALL, signed cursor, warehouse and arbitrary historic-type semantics in BOTH API paths", () => {
    for (const locationId of [11, 12]) {
      const detailedAll = buildLedgerCursorUrl({ locationId, referenceType: "ALL", cursor: "signed-cursor" });
      const operationsAll = buildLedgerOperationUrl({ locationId, referenceType: "ALL", cursor: "signed-cursor" });
      for (const url of [detailedAll, operationsAll]) {
        const params = new URL(url, "https://ledger.test").searchParams;
        expect(params.get("location_id")).toBe(String(locationId));
        expect(params.get("cursor")).toBe("signed-cursor");
        expect(params.has("reference_type")).toBe(false);
      }
      for (const url of [
        buildLedgerCursorUrl({ locationId, referenceType: "FUTURE_STOCK_EVENT", search: "historic" }),
        buildLedgerOperationUrl({ locationId, referenceType: "FUTURE_STOCK_EVENT", search: "historic" }),
      ]) {
        const params = new URL(url, "https://ledger.test").searchParams;
        expect(params.get("reference_type")).toBe("FUTURE_STOCK_EVENT");
        expect(params.get("search")).toBe("historic");
      }
    }
  });

  it("does not change reference-type identity when choosing Arabic options", () => {
    const selected = vi.fn();
    render(filters("ar", [], "ALL", selected));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "AUDIT_ADJUSTMENT" } });
    expect(selected).toHaveBeenCalledWith("AUDIT_ADJUSTMENT");
  });
});
