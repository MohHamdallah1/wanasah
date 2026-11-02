import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeDiscoveredModal } from "./StocktakeDiscoveredModal";
import { useStocktakeCounting } from "./hooks/useStocktakeCounting";
import { buildDiscoveredRow, parseDiscoveredBatches, restoreDiscoveredRows } from "./discoveredContract";
import type { StocktakeRow } from "../inventoryUtils";
import type { StocktakeAuthFetch } from "./types";

const language = vi.hoisted(() => ({ value: "ar" }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: language.value, resolvedLanguage: language.value },
    t: (key: string) => key,
  }),
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, title, children, footer }: {
    isOpen: boolean; title: string; children: React.ReactNode; footer: React.ReactNode;
  }) => isOpen ? <div role="dialog" aria-label={title}>{children}{footer}</div> : null,
}));
vi.mock("@/hooks/useInventoryAccess", () => ({
  parseInventoryCapabilities: (raw: unknown) => raw,
  hasInventoryPermission: () => true,
}));

const batch = {
  id: 22, product_variant_id: 11, batch_number: "TRUE-LOT-22",
  production_date: "2026-01-01", expiry_date: "2027-01-01",
  is_active: true, disposition: "RELEASED", product_name: "Real SKU",
  sku: "SKU11", base_uom_id: 3, base_uom_code: "EACH",
  base_uom_name: "Each", quantity_scale: 3, quantity_step: "0.250",
};
const page = (items: unknown[]) => ({
  items, next_cursor: null, has_more: false, total: null,
});
const product = {
  id: 11, name: "Real SKU", sku: "SKU11", base_uom_id: 3,
  base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 3, quantity_step: "0.250",
};

beforeEach(() => {
  localStorage.clear();
  language.value = "ar";
});

describe("V1 discovered physical stock and real Batch identity", () => {
  it("accepts only actual session-authorized Batch metadata and enforces UOM step", () => {
    const selected = parseDiscoveredBatches(page([batch]), 11).items[0];
    expect(buildDiscoveredRow(selected, "QUARANTINED", "1.250")).toMatchObject({
      batch_id: 22, line_origin: "DISCOVERED", stock_status: "QUARANTINED",
      actual_quantity: "1.25", counted: true,
    });
    expect(() => buildDiscoveredRow(selected, "AVAILABLE", "0.100")).toThrow();
    expect(() => parseDiscoveredBatches(page([{ ...batch, product_variant_id: 99 }]), 11)).toThrow();
    expect(() => restoreDiscoveredRows([
      { ...buildDiscoveredRow(selected, "AVAILABLE", "1.000"), batch_id: 999 },
    ], [selected], [])).toThrow();
    expect(() => restoreDiscoveredRows([
      buildDiscoveredRow(selected, "AVAILABLE", "1.000"),
    ], [selected], [buildDiscoveredRow(selected, "AVAILABLE", "1.000")])).toThrow();
  });

  it.each([["ar", "إضافة إلى مسودة العد"], ["en", "Add to count draft"]])(
    "adds real discovered stock with keyboard-accessible %s controls", async (lang, saveLabel) => {
      language.value = lang;
      const fetch: StocktakeAuthFetch = vi.fn(async (url) =>
        url.includes("product_variant_id=11") ? page([batch]) : page([product]));
      const onAdd = vi.fn(() => true);
      render(<StocktakeDiscoveredModal
        open sessionId="35" authenticatedFetch={fetch}
        onClose={vi.fn()} onAdd={onAdd}
      />);
      fireEvent.click(await screen.findByRole("button", { name: /Real SKU/ }));
      fireEvent.click(await screen.findByRole("button", { name: /TRUE-LOT-22/ }));
      const quantity = screen.getByLabelText(lang === "ar"
        ? /الكمية الفعلية بوحدة الأساس/ : /Actual quantity in base UOM/);
      fireEvent.change(quantity, { target: { value: "1.25" } });
      fireEvent.click(screen.getByRole("button", { name: saveLabel }));
      expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({
        line_origin: "DISCOVERED", product_variant_id: 11, batch_id: 22,
        stock_status: "QUARANTINED", actual_quantity: "1.25",
        base_uom_id: 3,
      }));
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/35/discovery-options?"));
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    },
  );

  it("restores a scoped, trusted discovered count draft with zero snapshot rows", async () => {
    const verified = parseDiscoveredBatches(page([batch])).items[0];
    const draft = buildDiscoveredRow(verified, "QUARANTINED", "2.500");
    const key = "wanasah_audit_draft:3:5:35";
    localStorage.setItem(key, JSON.stringify([draft]));
    const fetch: StocktakeAuthFetch = vi.fn(async (url) => {
      if (url.startsWith("/inventory/access/me")) return { location_id: 5 };
      if (url.endsWith("/35/count-sheet")) return [];
      if (url.includes("batch_ids=22")) return page([batch]);
      throw new Error("Unexpected request");
    });
    function useCountingWithRows() {
      const [rows, setRows] = useState<StocktakeRow[]>([]);
      const control = useStocktakeCounting({
        durableIdentity: { companyId: 3, backofficeUserId: 5 },
        companyScope: "3", phaseKey: "stocktake:phase", phase: "COUNTING",
        sessionId: "35", sessionLocationId: 5, draftKey: key,
        authenticatedFetch: fetch, rows, setRows, setReview: vi.fn(),
        setSessionId: vi.fn(), setSessionLocationId: vi.fn(), setPhase: vi.fn(),
        onSubmitted: vi.fn(async () => {}),
      });
      return { ...control, rows };
    }
    const { result, unmount } = renderHook(useCountingWithRows);
    await act(async () => { await result.current.loadCountSheet("35", 5); });
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    expect(result.current.rows[0]).toMatchObject({
      batch_id: 22, product_name: "Real SKU", line_origin: "DISCOVERED",
      actual_quantity: "2.5",
    });
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("batch_ids=22"));
    unmount();
  });
});
