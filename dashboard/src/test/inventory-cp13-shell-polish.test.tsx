import { useState } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { Boxes, FilePlus, History } from "lucide-react";
import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";

import { InventoryTopDock } from "@/pages/inventory/InventoryTopDock";
import { LedgerTable } from "@/pages/inventory/ledger/LedgerTable";
import { BatchIndexTable } from "@/pages/inventory/batches/BatchIndexTable";

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
  const translator = ((key: string) => key) as TFunction;

  it.each(["ltr", "rtl"])("keeps the same dock frame while permissions are pending (%s)", (dir) => {
    const onChange = vi.fn();
    const { container, rerender } = render(
      <div dir={dir}>
        <InventoryTopDock items={[]} loading activeId="live" ariaLabel="Inventory workflows" onChange={onChange} />
      </div>,
    );
    expect(container.querySelector(".workspace-top-bar-frame")).toBeInTheDocument();
    expect(screen.getByRole("tablist")).toHaveAttribute("aria-busy", "true");
    expect(container.querySelector('[data-inventory-dock-loading="true"]')).toBeInTheDocument();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);

    rerender(
      <div dir={dir}>
        <InventoryTopDock items={items} activeId="live" ariaLabel="Inventory workflows" onChange={onChange} />
      </div>,
    );
    expect(container.querySelector(".workspace-top-bar-frame")).toBeInTheDocument();
    expect(screen.getByRole("tablist")).toHaveAttribute("aria-busy", "false");
    expect(screen.getAllByRole("tab")).toHaveLength(items.length);
    expect(screen.getByRole("tab", { name: "Live stock" })).toHaveAttribute("aria-selected", "true");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps the pending data panel inside the shell, never as a flex sibling above all tabs", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");
    expect(shell).toContain('data-inventory-pending-surface="true"');
    expect(shell).toContain('activeTab === "live" && !liveVisible');
    expect(shell).toContain('activeTab !== "live" &&');
    expect(shell).not.toContain('if (loadingLocations && warehouseSetup === null && selectedLocationId === null) {');
    expect(shell).not.toMatch(/selectedLocationId !== null &&\s*!liveVisible &&\s*!accessDenied && \(/);
    expect(shell).toContain('!loadingLocations && activeTab !== "warehouses"');
  });

  it("keeps Inventory mounted across same-session dashboard navigation instead of rebuilding it", () => {
    const layout = read("src/components/operations/DashboardLayout.tsx");
    const app = read("src/App.tsx");

    expect(layout).toContain('data-persistent-inventory-host="true"');
    expect(layout).toContain('className={isInventoryRoute ? "contents" : "hidden"}');
    expect(layout).toContain('key={`${session.generation}:${session.identity}:inventory`}');
    expect(layout).toContain("setInventoryMounted(true)");
    expect(app).toContain('<Route path="/inventory" element={<Fragment />} />');
  });

  it("keeps desktop Ledger column headers mounted through load and empty states", () => {
    const renderTable = (loading: boolean) => <LedgerTable
      t={translator} language="en" locale="en" entries={[]}
      loading={loading} canAdjust={false}
      onOpenReference={() => undefined} onOpenNotes={() => undefined}
      onOpenAdjustment={() => undefined}
    />;
    const { container, rerender } = render(renderTable(true));
    const desktop = container.querySelector('table');
    expect(desktop?.querySelectorAll('thead th')).toHaveLength(12);
    expect(container.querySelector('td[data-cp13-state="loading"]')).toHaveTextContent("loading");
    rerender(renderTable(false));
    expect(container.querySelector('table')).toBe(desktop);
    expect(container.querySelector('td[data-cp13-state="empty"]')).toHaveTextContent("empty");
  });

  it("keeps desktop batch column headers and retry within one list frame", () => {
    const props = {
      t: translator, language: "en", locale: "en", items: [],
      hasMore: false, loadingMore: false, continuationError: false,
      canManageDisposition: false, onRetry: vi.fn(),
      onLoadMore: vi.fn(), onManage: vi.fn(),
    };
    const { container, rerender } = render(<BatchIndexTable {...props} loading error={false} />);
    const desktop = container.querySelector('table');
    expect(desktop?.querySelectorAll('thead th')).toHaveLength(7);
    expect(container.querySelector('td [data-cp13-state="loading"]')).toBeInTheDocument();
    rerender(<BatchIndexTable {...props} loading={false} error />);
    expect(container.querySelector('table')).toBe(desktop);
    expect(container.querySelector('td [data-cp13-state="error"]')).toBeInTheDocument();
    expect(container.querySelector('td button')).toHaveTextContent("retry");
  });

  it("keeps Warehouse context visible without changing capability-driven workflow visibility", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");
    const live = read("src/pages/inventory/Tab1LiveStock.tsx");

    expect(shell).toContain("TABS.filter((tab) => tabAllowed(tab.id))");
    expect(shell).toContain('activeTab !== "live"');
    expect(shell).toContain('aria-label={t("inventoryShell.warehouseSelectLabel")}');
    expect(shell).toContain('warehouseSetup?.warehouse_ready === false');
    expect(shell).toContain("requiresFirstWarehouse");
    expect(shell).toContain('toast.info(t("inventoryShell.createWarehouseFirstNotice"))');
    expect(shell).toContain('setActiveTab("warehouses")');
    expect(live).toContain("<LiveStockWarehouseContext");
    expect(live).toMatch(/onLocationChange=\{\(value\) => \{\s*resetRenderWindow\(\);\s*onLocationChange\(value\);/);
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

  it("locks outer top-bar geometry to the shared WorkspaceTopBar only", () => {
    const dock = read("src/pages/inventory/InventoryTopDock.tsx");
    const shared = read("src/components/dashboard/WorkspaceTopBar.css");
    const inventoryCss = read("src/pages/inventory/inventory.css");
    const polish = read("src/pages/inventory/inventoryShellPolish.css");

    expect(dock).toContain("<WorkspaceTopBar");
    expect(dock).toContain('variant="dock"');
    expect(dock).not.toContain("inventory-top-dock-component");
    expect(inventoryCss).not.toContain(".inventory-top-dock-component");
    expect(polish).not.toContain(".inventory-top-dock-component");

    expect(shared).toContain("width: calc(100% + 2rem) !important;");
    expect(shared).toContain("height: 3.75rem !important;");
    expect(shared).toContain("min-height: 3.75rem !important;");
    expect(shared).toContain("max-height: 3.75rem !important;");
    expect(shared).toContain("margin-block-start: -1.5rem !important;");
    expect(shared).toContain("margin-inline: -1rem !important;");
    expect(shared).toContain("flex: 0 0 3.75rem !important;");

    expect(polish).toContain("padding-inline: 0 !important;");
    expect(polish).toContain('.inventory-workspace:not([data-live-view="true"]) > :not(.workspace-top-bar-frame)');
    expect(polish).toContain("overflow-x: auto;");
    expect(polish).toContain("background: rgb(255 255 255 / 0.06);");
    expect(polish).toContain("background: #fbbf24;");
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
  it("keeps a non-sensitive Live Stock table frame while fresh access is verified", () => {
    const shell = read("src/pages/inventory/MainInventory.tsx");
    const css = read("src/pages/inventory/inventory.css");
    const detail = read("src/pages/inventory/liveStock/BatchDetailPanel.tsx");
    expect(shell).toContain('data-live-verification-shell="true"');
    expect(shell).toContain('live={activeTab === "live"}');
    expect(shell).toContain('stockItemsRef.current = []');
    expect(shell).toContain('!liveVisible');
    expect(css).toContain("flex-wrap: nowrap;");
    expect(css).toContain("overscroll-behavior-inline: contain;");
    expect(detail).toContain("batch.expiry_unavailable_quantity");
    expect(detail).toContain("batch.restricted_quantity");
    expect(detail).toContain("batch.disposition_reason");
  });

  it("keeps arrow/Home/End focus on the activated tab when its panel autofocuses an editor", () => {
    function Harness() {
      const [active, setActive] = useState("live");
      return <>
        <InventoryTopDock items={items} activeId={active} ariaLabel="Inventory workflows" onChange={setActive} />
        {active === "ledger" && <input autoFocus aria-label="Panel editor" />}
      </>;
    }
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "End" });
    expect(tabs[2]).toHaveFocus();
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[2], { key: "Home" });
    expect(tabs[0]).toHaveFocus();
  });

});
