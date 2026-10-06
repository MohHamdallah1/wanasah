from __future__ import annotations

import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST = ROOT / "dashboard" / "src" / "test" / "batch-focus-workspace.test.tsx"
CATALOG_TEST = ROOT / "dashboard" / "src" / "test" / "catalog-inventory-boundary.test.ts"
STATUS_TEST = ROOT / "dashboard" / "src" / "test" / "products-status-summary.test.tsx"
RULES = ROOT / ".rules"
MAIN_NODE_MODULES = pathlib.Path(r"C:\Users\admin\Desktop\wanasah\dashboard\node_modules")
WORKTREE_NODE_MODULES = ROOT / "dashboard" / "node_modules"
BRANCH = "fix/simplify-batch-quality-ux"


def run(*args: str, cwd: pathlib.Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=str(cwd or ROOT), check=True)


old_first = '''  const matrix: Array<[string, ReturnType<typeof batchSource>[]]> = [
    ["one warehouse", [batchSource(11, "Warehouse A")]],
    ["two warehouses", [batchSource(11, "Warehouse A"), batchSource(12, "Warehouse B")]],
    ["warehouse and vehicle", [batchSource(11, "Warehouse A"), batchSource(13, "Vehicle 13", "VEHICLE")]],
    ["vehicle only", [batchSource(13, "Vehicle 13", "VEHICLE")]],
  ];
  it.each(matrix)("opens Products warning for %s independently of last selected warehouse", async (_label, sources) => {
    mockReads(batchFocusPayload(sources));
    const { i18n } = await mount({ products: true });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("products.commercialStatus.batchRestrictionOpen") }));
    await screen.findByText("LOT-41");
    for (const source of sources) expect(screen.getAllByText(source.location_name).length).toBeGreaterThan(0);
    expect(mocks.shell).not.toHaveBeenCalled();
    expect(localStorage.getItem("inventory_selected_location:1")).toBe("999");
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
    expect(screen.queryByText("Untrusted navigation label")).not.toBeInTheDocument();
    if (sources.length === 1) expect(screen.getByText(i18n.t("batchFocus.singleSource", { source: sources[0].location_name }))).toBeVisible();
    else expect(screen.getByText(i18n.t("batchFocus.multipleSources", { count: "2" }))).toBeVisible();
    expect(mocks.fetch.mock.calls.filter(([url]) => url === "/warehouse/batches/41/stock-sources")).toHaveLength(1);
    expect(mocks.fetch.mock.calls.some(([url]) => String(url).includes("location_id=999"))).toBe(false);
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.openTransfers") })).not.toBeInTheDocument();
  });

'''
new_first = '''  it("keeps the Products batch warning compact and opens company-wide batch management", async () => {
    const candidatesUrl = "/warehouse/variants/118/quality-batch-candidates?limit=25";
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url === "/inventory/access/me") return inventoryReadAccess();
      if (url === candidatesUrl) {
        return {
          product_variant_id: 118,
          base_uom_id: 7,
          base_uom_code: "EACH",
          items: [{
            batch_id: 41,
            batch_number: "LOT-41",
            production_date: "2026-09-01",
            expiry_date: "2027-09-01",
            disposition: "QUARANTINED",
            disposition_reason: "Saved inspection reason",
            total_on_hand_quantity: "13",
            total_reserved_quantity: "4",
            source_count: 2,
            sources_preview: [
              { location_id: 13, location_name: "Vehicle 13", location_type: "VEHICLE", on_hand_quantity: "3", reserved_quantity: "2" },
              { location_id: 11, location_name: "Warehouse A", location_type: "WAREHOUSE", on_hand_quantity: "10", reserved_quantity: "2" },
            ],
            sources_truncated: false,
          }],
          next_cursor: null,
          has_more: false,
        };
      }
      throw new Error(`Unexpected read: ${url}`);
    });

    const { i18n } = await mount({ products: true, language: "ar" });
    expect(screen.getByText(i18n.t("productQualityWorkspace.affectedBatchesCompact", { count: 1 }))).toBeVisible();
    expect(i18n.t("productQualityWorkspace.affectedBatchesCompact", { count: 2 })).toBe("دفعتان متوقفتان");
    expect(i18n.t("productQualityWorkspace.affectedBatchesCompact", { count: 3 })).toBe("3 دفعات متوقفة");
    expect(screen.queryByText("Saved inspection reason")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: i18n.t("productQualityWorkspace.manageAffectedBatches"),
    }));

    await screen.findByRole("heading", {
      level: 2,
      name: i18n.t("productQualityWorkspace.batchPicker.batch", { batch: "LOT-41" }),
    });
    expect(screen.getByText("Warehouse A · 10 EACH")).toBeVisible();
    expect(screen.getByText("Vehicle 13 · 3 EACH")).toBeVisible();
    expect(screen.getByText(i18n.t("productQualityWorkspace.batchPicker.distributed", { count: "2" }))).toBeVisible();
    expect(mocks.shell).not.toHaveBeenCalled();
    expect(localStorage.getItem("inventory_selected_location:1")).toBe("999");
    expect(mocks.fetch.mock.calls.some(([url]) => String(url).includes("location_id=999"))).toBe(false);
    expect(mocks.fetch.mock.calls.filter(([url]) => url === "/warehouse/batches/41/stock-sources")).toHaveLength(0);
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });

'''
old_tail = '''    fireEvent.click(screen.getAllByRole("button", {
      name: i18n.t("productQualityWorkspace.batchPicker.open"),
    })[0]);
    await screen.findByRole("heading", { level: 2, name: "LOT-41" });
    expect(screen.getAllByText("Warehouse A").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vehicle 13").length).toBeGreaterThan(0);
    expect(mocks.fetch.mock.calls.filter(([url]) => url === candidatesUrl)).toHaveLength(1);
    expect(mocks.fetch.mock.calls.filter(([url]) => url === "/warehouse/batches/41/stock-sources")).toHaveLength(1);
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
'''
new_tail = '''    fireEvent.click(screen.getAllByRole("button", {
      name: i18n.t("productQualityWorkspace.batchPicker.open"),
    })[0]);
    await screen.findByText("Saved inspection reason", { exact: false });
    expect(screen.getByRole("heading", {
      level: 2,
      name: i18n.t("productQualityWorkspace.batchPicker.batch", { batch: "LOT-41" }),
    })).toBeVisible();
    expect(screen.getByRole("heading", {
      level: 2,
      name: i18n.t("productQualityWorkspace.batchPicker.batch", { batch: "LOT-42" }),
    })).toBeVisible();
    expect(screen.getByText("Warehouse A · 10 EACH")).toBeVisible();
    expect(screen.getByText("Vehicle 13 · 3 EACH")).toBeVisible();
    expect(screen.getByText("Warehouse C · 7 EACH")).toBeVisible();
    expect(screen.queryByText(i18n.t("batchFocus.title"))).not.toBeInTheDocument();
    expect(mocks.fetch.mock.calls.filter(([url]) => url === candidatesUrl)).toHaveLength(1);
    expect(mocks.fetch.mock.calls.filter(([url]) => url === "/warehouse/batches/41/stock-sources").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
'''

text = TEST.read_text(encoding="utf-8")
if old_first not in text:
    raise RuntimeError("old Products warning test block not found")
if old_tail not in text:
    raise RuntimeError("old company-wide batch test tail not found")
TEST.write_text(text.replace(old_first, new_first, 1).replace(old_tail, new_tail, 1), encoding="utf-8")

catalog_old = '''  it("keeps exact batch focus as a read-only navigation hint resolved by Inventory", () => {
    const statusBadges = read(
      "../pages/products/list/ProductStatusBadges.tsx",
    );
    const batches = read("../pages/inventory/TabBatches.tsx");

    expect(statusBadges).toContain(
      "restrictions.representative_reason?.batch_id",
    );
    expect(statusBadges).toContain(
      "createInventoryBatchFocusNavigationState",
    );
    expect(statusBadges).not.toContain("authFetch(");
'''
catalog_new = '''  it("keeps Products navigation as a read-only company-wide batch hint resolved by Inventory", () => {
    const statusBadges = read(
      "../pages/products/list/ProductStatusBadges.tsx",
    );
    const batches = read("../pages/inventory/TabBatches.tsx");

    expect(statusBadges).toContain("batchId: null");
    expect(statusBadges).not.toContain(
      "restrictions.representative_reason?.batch_id",
    );
    expect(statusBadges).toContain(
      "createInventoryBatchFocusNavigationState",
    );
    expect(statusBadges).not.toContain("authFetch(");
'''
catalog_text = CATALOG_TEST.read_text(encoding="utf-8")
if catalog_old not in catalog_text:
    raise RuntimeError("old Catalog/Inventory boundary assertion not found")
CATALOG_TEST.write_text(catalog_text.replace(catalog_old, catalog_new, 1), encoding="utf-8")

status_old = '''    expect(screen.getByText("متاح للبيع")).toBeInTheDocument();
    expect(
      screen.getByText("المنتج نشط، لكن 2 دفعة غير متاحة للبيع."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("السبب: اشتباه في جودة المنتج"),
    ).toBeInTheDocument();
    const openBatch = screen.getByRole("button", {
      name: "فتح الدفعة المتأثرة",
    });
    openBatch.focus();
    expect(openBatch).toHaveFocus();
    fireEvent.click(openBatch);
    expect(JSON.parse(screen.getByTestId("route-state").textContent ?? "{}")).toEqual({
      pathname: "/inventory",
      state: {
        inventoryNavigation: {
          version: 1,
          kind: "batch-focus",
          tab: "batches",
          variantId: 118,
          batchId: 41,
          productName: "منتج اختبار",
          locationId: null,
        },
      },
    });
'''
status_new = '''    expect(screen.getByText("متاح للبيع")).toBeInTheDocument();
    expect(screen.getByText("دفعتان متوقفتان")).toBeInTheDocument();
    expect(screen.queryByText("اشتباه في جودة المنتج", { exact: false })).not.toBeInTheDocument();
    expect(screen.queryByText("معزولة للفحص")).not.toBeInTheDocument();
    expect(screen.queryByText("ممنوعة من البيع")).not.toBeInTheDocument();
    const openBatch = screen.getByRole("button", {
      name: "فتح الدفعات المتأثرة",
    });
    openBatch.focus();
    expect(openBatch).toHaveFocus();
    fireEvent.click(openBatch);
    expect(JSON.parse(screen.getByTestId("route-state").textContent ?? "{}")).toEqual({
      pathname: "/inventory",
      state: {
        inventoryNavigation: {
          version: 1,
          kind: "batch-focus",
          tab: "batches",
          variantId: 118,
          batchId: null,
          productName: "منتج اختبار",
          locationId: null,
        },
      },
    });
'''
status_text = STATUS_TEST.read_text(encoding="utf-8")
if status_old not in status_text:
    raise RuntimeError("old product status presentation assertion not found")
STATUS_TEST.write_text(status_text.replace(status_old, status_new, 1), encoding="utf-8")

ux_rules = '''DASHBOARD UX CONSTITUTION (MANDATORY):
- Backend complexity must not leak into the operator experience. Preserve all authority, validation, audit, isolation, idempotency, and safety in backend/domain layers while keeping the dashboard path short and obvious.
- Every page/workspace must have one clear operational responsibility. Do not create intermediary pages whose main purpose is to forward the user to the real action.
- Prefer the fewest safe clicks to the canonical owner workflow. Reuse the existing authoritative page/workspace instead of adding duplicate or puzzle-like navigation layers.
- A busy operator must be able to understand the current state, the next valid action, and any blocker at a glance. Avoid paragraph-heavy table cells, repeated explanations, and hidden multi-step discovery.
- Cross-location inventory truth may remain complex and backend-authoritative, but the UI must summarize it clearly (for example, one batch distributed across several warehouses/vehicles) without forcing the user to visit each location manually.
- Simplifying UX must never remove a capability, weaken permissions, move business authority into React, or duplicate domain rules. Simplify presentation and navigation, not correctness.

'''
rules = RULES.read_text(encoding="utf-8")
if "DASHBOARD UX CONSTITUTION (MANDATORY):" not in rules:
    marker = "Role & Objective:\n"
    if marker not in rules:
        raise RuntimeError("Role & Objective marker not found in .rules")
    RULES.write_text(rules.replace(marker, ux_rules + marker, 1), encoding="utf-8")

if not WORKTREE_NODE_MODULES.exists():
    run("cmd", "/c", "mklink", "/J", str(WORKTREE_NODE_MODULES), str(MAIN_NODE_MODULES))

run("git", "diff", "--check")
node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
vitest = MAIN_NODE_MODULES / "vitest" / "vitest.mjs"
vite = MAIN_NODE_MODULES / "vite" / "bin" / "vite.js"
if not vitest.exists() or not vite.exists():
    raise RuntimeError("dashboard node_modules does not contain Vitest/Vite")

dashboard = ROOT / "dashboard"
run(node, str(vitest), "run",
    "src/test/batch-focus-workspace.test.tsx",
    "src/test/products-lifecycle-guided-recovery.test.ts",
    "src/test/products-enter-recall-ux.test.ts",
    "src/test/products-status-summary.test.tsx",
    "src/test/catalog-inventory-boundary.test.ts",
    "src/test/quality-safety-v1-closure.test.ts", cwd=dashboard)
run(node, str(vite), "build", cwd=dashboard)

run("git", "add", ".rules",
    "dashboard/src/test/batch-focus-workspace.test.tsx",
    "dashboard/src/test/catalog-inventory-boundary.test.ts",
    "dashboard/src/test/products-status-summary.test.tsx")
run("git", "rm", "tools/_tmp_quality_ux_patch.py")
run("git", "commit", "-m", "test(ux): lock simplified batch quality flow")
run("git", "push", "origin", f"HEAD:{BRANCH}")
run("git", "status", "--short")
run("git", "rev-parse", "HEAD")
