import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { Boxes, FilePlus, History } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { InventoryTopDock } from "@/pages/inventory/InventoryTopDock";

vi.mock("@/pages/inventory/inventoryTopDockController", () => ({
  createInventoryTopDockController: () => () => undefined,
}));

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

const items = [
  { id: "live", label: "Live stock", icon: Boxes },
  { id: "inbound", label: "Inbound receipt", icon: FilePlus },
  { id: "ledger", label: "Movement ledger", icon: History },
] as const;

describe("CP13.2 Inventory shell polish", () => {
  it("keeps Warehouse context visible without changing capability-driven workflow visibility", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");
    const live = read("src/pages/inventory/Tab1LiveStock.tsx");

    expect(shell).toContain("TABS.filter((tab) => tabAllowed(tab.id))");
    expect(shell).toContain('activeTab !== "live"');
    expect(shell).toContain('aria-label={t("inventoryShell.warehouseSelectLabel")}');
    expect(live).toContain("<LiveStockWarehouseContext");
    expect(live).toContain("onLocationChange={onLocationChange}");
  });

  it("marks the active workflow explicitly and keeps long translated labels intact", () => {
    const longLabel = "Long translated warehouse workflow label for compact shell acceptance";
    render(
      <div dir="ltr">
        <InventoryTopDock
          items={[...items, { id: "long", label: longLabel, icon: History }]}
          activeId="long"
          ariaLabel="Inventory workflows"
          onChange={() => undefined}
        />
      </div>,
    );

    const active = screen.getByRole("tab", { name: longLabel });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active).toHaveAttribute("data-active", "true");
    expect(active).toHaveAttribute("title", longLabel);
    expect(active).toHaveAttribute("tabindex", "0");
  });

  it("keeps deep-link consumption and persisted tab/Warehouse state contracts unchanged", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");

    expect(shell).toContain("parseInventoryNavigationState(routeLocation.state)");
    expect(shell).toContain("inventory_active_tab:${companyId}");
    expect(shell).toContain("inventory_selected_location:${companyId}");
    expect(shell).toContain("{ replace: true, state: null }");
  });

  it("removes the cross-workflow shared Live refresh while preserving the Live-local refresh", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");
    const css = read("src/pages/inventory/inventoryShellPolish.css");

    expect(css).toMatch(/inventory-shared-context-row \.inventory-sync[\s\S]*?display:\s*none/);
    expect(shell).toContain('activeTab === "live"');
    expect(shell).toContain("onRefresh={() => {");
    expect(shell).toContain("refreshStock();");
    expect(shell).toContain("void fetchStatus();");
  });

  it("preserves logical LTR and RTL arrow navigation with visible roving focus", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <div dir="ltr">
        <InventoryTopDock items={items} activeId="inbound" ariaLabel="Inventory workflows" onChange={onChange} />
      </div>,
    );

    let tabs = screen.getAllByRole("tab");
    tabs[1].focus();
    fireEvent.keyDown(tabs[1], { key: "ArrowRight" });
    expect(tabs[2]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("ledger");

    rerender(
      <div dir="rtl">
        <InventoryTopDock items={items} activeId="inbound" ariaLabel="مسارات المخزون" onChange={onChange} />
      </div>,
    );
    tabs = screen.getAllByRole("tab");
    tabs[1].focus();
    fireEvent.keyDown(tabs[1], { key: "ArrowRight" });
    expect(tabs[0]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("live");

    const css = read("src/pages/inventory/inventoryShellPolish.css");
    expect(css).toContain("outline: 3px solid");
    expect(css).toContain('html[dir="rtl"]');
  });

  it("keeps Arabic/English labels native and forces Western numeric presentation", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");
    const css = read("src/pages/inventory/inventoryShellPolish.css");

    render(
      <div dir="rtl">
        <InventoryTopDock
          items={[{ id: "inbound", label: "توريد بضاعة", icon: FilePlus }]}
          activeId="inbound"
          ariaLabel="أقسام المخزون"
          onChange={() => undefined}
        />
      </div>,
    );
    expect(screen.getByRole("tab", { name: "توريد بضاعة" })).toBeInTheDocument();
    expect(shell).toContain('numberingSystem: "latn"');
    expect(css).toContain("font-variant-numeric: lining-nums tabular-nums");
  });

  it("keeps the dock usable at phone width without allowing long labels to break layout", () => {
    const css = read("src/pages/inventory/inventoryShellPolish.css");

    expect(css).toContain("@media (max-width: 640px)");
    expect(css).toContain("overflow-x: auto");
    expect(css).toContain("scroll-snap-type: inline proximity");
    expect(css).toContain("text-overflow: ellipsis");
    expect(css).toContain("max-width: 10.75rem");
    expect(css).toContain("width: 100%");
  });
});
