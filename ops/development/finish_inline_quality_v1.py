from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "dashboard"


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected block missing: {path} :: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Wire the small, separately-maintained i18n block into the main resources.
resources = DASH / "src/i18n/resources.ts"
replace(resources,
        'import { productQualityWorkspace } from "./productQualityWorkspace";\n',
        'import { productQualityWorkspace } from "./productQualityWorkspace";\nimport { productQualityInline } from "./productQualityInline";\n')
replace(resources,
        '      productQualityWorkspace: productQualityWorkspace.ar,\n',
        '      productQualityWorkspace: productQualityWorkspace.ar,\n      productQualityInline: productQualityInline.ar,\n')
replace(resources,
        '      productQualityWorkspace: productQualityWorkspace.en,\n',
        '      productQualityWorkspace: productQualityWorkspace.en,\n      productQualityInline: productQualityInline.en,\n')
replace(resources,
        '        cancel: "إلغاء",\n        close: "إغلاق",\n',
        '        cancel: "إلغاء",\n        confirm: "تأكيد",\n        close: "إغلاق",\n')
replace(resources,
        '        cancel: "Cancel",\n        close: "Close",\n',
        '        cancel: "Cancel",\n        confirm: "Confirm",\n        close: "Close",\n')

# Correct bidi direction for the inline panel.
panel = DASH / "src/features/inventory/quality/WholeProductQualityActionsPanel.tsx"
replace(panel, '  const { t } = useTranslation();\n', '  const { t, i18n } = useTranslation();\n')
replace(panel,
        '  return <div className="space-y-3" dir={t("common.direction", { defaultValue: "rtl" })}>\n',
        '  return <div className="space-y-3" dir={i18n.dir()}>\n')

# Make the focused model proof independent of locale sort order.
model_test = DASH / "src/test/product-quality-inline-location.test.ts"
replace(model_test,
        '    expect(locations).toHaveLength(2);\n    expect(locations[1].locationName).toBe("مستودع التطوير");\n    expect(locations[1].onHandQuantity).toBe("100");\n    expect(locations[1].reservedQuantity).toBe("10");\n    expect(locations[1].movableQuantity).toBe("90");\n    expect(locations[1].batchIds).toEqual([101, 102]);\n    expect(actionTotal(locations[1].dispatch.DISPOSAL)).toBe("90");\n    expect(actionTotal(locations[1].dispatch.RETURN_TO_VENDOR)).toBe("50");\n    expect(locations[0].needsDestinationSetup).toBe(true);\n',
        '    expect(locations).toHaveLength(2);\n    const development = locations.find((item) => item.locationId === 7)!;\n    const second = locations.find((item) => item.locationId === 8)!;\n    expect(development.locationName).toBe("مستودع التطوير");\n    expect(development.onHandQuantity).toBe("100");\n    expect(development.reservedQuantity).toBe("10");\n    expect(development.movableQuantity).toBe("90");\n    expect(development.batchIds).toEqual([101, 102]);\n    expect(actionTotal(development.dispatch.DISPOSAL)).toBe("90");\n    expect(actionTotal(development.dispatch.RETURN_TO_VENDOR)).toBe("50");\n    expect(second.needsDestinationSetup).toBe(true);\n')

# Replace V1 closure assertions that intentionally protected the now-removed
# intermediate whole-product Inventory page.
quality_test = DASH / "src/test/quality-safety-v1-closure.test.ts"
quality_test.write_text('''import { readFileSync } from "node:fs";\nimport { resolve } from "node:path";\nimport { describe, expect, it } from "vitest";\n\nconst read = (relativePath: string) =>\n  readFileSync(resolve(process.cwd(), "src/test", relativePath), "utf8");\n\ndescribe("V1 quality and safety workflow closure", () => {\n  it("records a whole-product issue without forcing navigation away from Products", () => {\n    const actions = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");\n    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");\n    expect(actions).not.toContain('payload.command === "recall"');\n    expect(actions).toContain("onManageWholeProductIssue");\n    expect(manager).toContain("<WholeProductQualityActionsPanel");\n    expect(manager).toContain("onManageWholeProductIssue={() => setQualityOpen(true)}");\n    expect(manager).not.toContain("createInventoryWholeProductIssueNavigationState");\n  });\n\n  it("keeps one primary affected-quantity action and hosts Inventory-owned commands through a shared feature", () => {\n    const panel = read("../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");\n    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");\n    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");\n    expect(panel).toContain("recallReadyToClose ?");\n    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');\n    expect(manager).toContain("WholeProductQualityActionsPanel");\n    expect(manager).not.toContain("@/pages/inventory/");\n    expect(inline).toContain("useProductQualityCommands");\n    expect(inline).toContain("products.qualityInline.actions.dispose");\n    expect(inline).toContain("products.qualityInline.actions.returnVendor");\n    expect(inline).toContain("products.qualityInline.actions.confirmDisposal");\n    expect(inline).toContain("products.qualityInline.actions.confirmVendor");\n  });\n\n  it("keeps handling-destination setup inline instead of redirecting the operator", () => {\n    const sharedCard = read("../features/inventory/quality/QualityHandlingDestinationsCard.tsx");\n    const wrapper = read("../pages/inventory/warehouse-locations/QualityHandlingDestinationsCard.tsx");\n    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");\n    const warehouses = read("../pages/inventory/TabWarehouseLocations.tsx");\n    expect(sharedCard).toContain('access.can("inventory.transfer_policy.manage")');\n    expect(sharedCard).toContain('/warehouse/operational-policy/transfer-destinations");\n    expect(wrapper).toContain("@/features/inventory/quality/QualityHandlingDestinationsCard");\n    expect(warehouses).toContain("<QualityHandlingDestinationsCard />");\n    expect(inline).toContain("<QualityHandlingDestinationsCard compact");\n    expect(inline).not.toContain('navigate("/inventory"');\n  });\n\n  it("uses plain business wording for the post-stop handling journey", () => {\n    const resources = read("../i18n/resources.ts");\n    const inlineTranslations = read("../i18n/productQualityInline.ts");\n    expect(resources).toContain('manageConfirmedIssue: "معالجة الكميات المتأثرة"');\n    expect(resources).toContain('closeRecall: "إغلاق المشكلة وإعادة البيع"');\n    expect(inlineTranslations).toContain('dispose: "إتلاف"');\n    expect(inlineTranslations).toContain('returnVendor: "إرجاع للمورد / المصنع"');\n    expect(inlineTranslations).toContain('confirmDisposal: "تأكيد الإتلاف"');\n    expect(inlineTranslations).toContain('confirmVendor: "تأكيد التسليم"');\n  });\n});\n''', encoding="utf-8")

# Update the architecture test: whole-product handling remains Inventory-owned,
# but is now embedded as a feature instead of navigating to an Inventory page.
boundary = DASH / "src/test/catalog-inventory-boundary.test.ts"
text = boundary.read_text(encoding="utf-8")
text = text.replace('  createInventoryWholeProductIssueNavigationState,\n', '')
quality_state = re.compile(r'\n    const qualityState = createInventoryWholeProductIssueNavigationState\(\{.*?\n    \}\);\n', re.S)
text, count = quality_state.subn('\n', text, count=1)
if count != 1:
    raise RuntimeError("quality navigation test block not found")
old_test = re.compile(r'  it\("keeps whole-product physical handling Inventory-owned and lifecycle closure Catalog-owned", \(\) => \{.*?\n  \}\);\n', re.S)
new_test = '''  it("keeps whole-product physical handling Inventory-owned while Products only hosts the shared feature", () => {\n    const lifecycle = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");\n    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");\n    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");\n\n    expect(lifecycle).toContain("WholeProductQualityActionsPanel");\n    expect(lifecycle).not.toContain("/warehouse/unified/transfer/special/dispatch");\n    expect(lifecycle).not.toContain("/warehouse/quality/disposal/confirm");\n    expect(lifecycle).not.toContain("/warehouse/quality/vendor-return/confirm");\n    expect(inline).toContain("useProductQualityCommands");\n    expect(commands).toContain("/warehouse/unified/transfer/special/dispatch");\n    expect(commands).toContain("/warehouse/quality/disposal/confirm");\n    expect(commands).toContain("/warehouse/quality/vendor-return/confirm");\n    expect(commands).not.toContain("close-recall");\n    expect(commands).not.toContain("cancel-recall");\n  });\n'''
text, count = old_test.subn(new_test, text, count=1)
if count != 1:
    raise RuntimeError("old physical handling boundary test not found")
boundary.write_text(text, encoding="utf-8")

# Remove the obsolete whole-product full-page workspace test. The product-wide
# flow is now proved by the inline location model and V1 closure tests.
old_workspace_test = DASH / "src/test/whole-product-quality-workspace.test.tsx"
if old_workspace_test.exists():
    old_workspace_test.unlink()

# Record the requested V1 accountability surface; backend evidence already exists.
audit = ROOT / "V1_COMPLETION_AUDIT.md"
audit_text = audit.read_text(encoding="utf-8")
activity_line = "- [ ] إضافة تبويب «سجل النشاط» داخل المنتج في V1: الإجراء، المنفذ، الوقت، السبب، والحالة قبل/بعد اعتمادًا على سجل التدقيق الموجود في الخادم."
if activity_line not in audit_text:
    marker = "## ما تبقى قبل اعتبار V1 جاهزًا\n"
    if marker not in audit_text:
        raise RuntimeError("V1 audit marker not found")
    audit_text = audit_text.replace(marker, marker + "\n" + activity_line + "\n", 1)
    audit.write_text(audit_text, encoding="utf-8")

# Keep the company-wide audit center explicitly out of V1 scope.
v2 = ROOT / "VERSION_2_FUTURE_FEATURES.md"
v2_text = v2.read_text(encoding="utf-8")
global_audit = '''\n\n## Company-wide audit center\n- Build a central, filterable company audit center in V2 for cross-module activity.\n- V1 still requires the product-local «سجل النشاط» so product actions are accountable without making the operator leave the product workflow.\n- Reuse immutable `domain_audit_events`; do not create a second audit authority in the frontend.\n'''
if "## Company-wide audit center" not in v2_text:
    v2.write_text(v2_text.rstrip() + global_audit + "\n", encoding="utf-8")

# Fail if the removed route symbols are still referenced by production code.
production = [
    DASH / "src/features/inventory/navigation.ts",
    DASH / "src/features/inventory/workspaceFocusNavigation.ts",
    DASH / "src/pages/inventory/InventoryPage.tsx",
    DASH / "src/pages/products/lifecycle/ProductLifecycleManager.tsx",
]
for path in production:
    source = path.read_text(encoding="utf-8")
    if "createInventoryWholeProductIssueNavigationState" in source or 'kind: "quality"' in source or 'kind === "quality"' in source:
        raise RuntimeError(f"obsolete whole-product route remains: {path}")

# Focused tests + production build. Use the already-installed root node_modules
# through the worktree junction; never install packages here.
vitest = DASH / "node_modules/vitest/vitest.mjs"
vite = DASH / "node_modules/vite/bin/vite.js"
focused = [
    "src/test/product-quality-inline-location.test.ts",
    "src/test/products-enter-recall-ux.test.ts",
    "src/test/quality-safety-v1-closure.test.ts",
    "src/test/catalog-inventory-boundary.test.ts",
    "src/test/whole-product-quality-readiness.test.tsx",
    "src/test/batch-terminal-actions.test.tsx",
    "src/test/inventory-batch-stock-sources.test.ts",
    "src/test/products-lifecycle-guided-recovery.test.ts",
    "src/test/product-translations-p7.test.ts",
]
subprocess.run(["node", str(vitest), "run", *focused], cwd=DASH, check=True)
subprocess.run(["node", str(vite), "build"], cwd=DASH, check=True)
subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
print("INLINE_QUALITY_GATE_PASS")
