from __future__ import annotations

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
MAIN_NODE_MODULES = pathlib.Path(r"C:\Users\admin\Desktop\wanasah\dashboard\node_modules")
WORKTREE_NODE_MODULES = DASHBOARD / "node_modules"
NODE = pathlib.Path(r"C:\Program Files\nodejs\node.exe")
BRANCH = "fix/whole-product-quality-ux-direct-actions"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def run(*args: str, cwd: pathlib.Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=str(cwd or ROOT), check=True)


# 1) Suppress repeated per-source destination setup cards when the parent workspace
# already presents the single authoritative setup requirement.
path = "dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx"
text = read(path)
text = replace_once(
    text,
    "  showTransferListLink?: boolean;\n  header?: ReactNode;\n};",
    "  showTransferListLink?: boolean;\n  header?: ReactNode;\n  suppressDestinationSetupPrompt?: boolean;\n};",
    "quantity props",
)
text = replace_once(
    text,
    "  showTransferListLink = false,\n  header,\n}: Props) {",
    "  showTransferListLink = false,\n  header,\n  suppressDestinationSetupPrompt = false,\n}: Props) {",
    "quantity destructure",
)
text = replace_once(
    text,
    "                ) ? (\n                  <div className=\"mt-2 rounded-lg border border-amber-200 bg-amber-50/70 p-3\">",
    "                ) ? (\n                  suppressDestinationSetupPrompt ? null : (\n                    <div className=\"mt-2 rounded-lg border border-amber-200 bg-amber-50/70 p-3\">",
    "setup prompt open",
)
text = replace_once(
    text,
    "                    ) : null}\n                  </div>\n                ) : (\n                  <div className=\"mt-2 rounded-lg border border-slate-200 bg-slate-50/70 p-2.5\">",
    "                    ) : null}\n                    </div>\n                  )\n                ) : (\n                  <div className=\"mt-2 rounded-lg border border-slate-200 bg-slate-50/70 p-2.5\">",
    "setup prompt close",
)
write(path, text)

# 2) Product-status drawer: exactly two primary recovery choices, plus only a compact
# location/batch summary. Backend readiness/blocker authority remains untouched.
path = "dashboard/src/features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx"
text = read(path)
helper_start = text.index("const recallBlockerHasOwnerAction")
helper_end = text.index("export function CatalogLifecycleSimplePanel", helper_start)
text = text[:helper_start] + text[helper_end:]

start = text.index("          {showProblemRecovery &&\n          canHold ? (")
end = text.index("\n          {showDraftActivation &&", start)
replacement = '''          {showProblemRecovery &&\n          canHold ? (\n            <>\n              <ActionItem\n                icon={<Play className="h-3.5 w-3.5" />}\n                label={t(\n                  "catalogLifecycle.actions.cancelRecall",\n                )}\n                hint={t(\n                  "catalogLifecycle.simple.actionHints.cancelRecall",\n                )}\n                disabled={actionsDisabled}\n                onClick={() =>\n                  onChooseCommand(\n                    "cancel-recall",\n                  )\n                }\n              />\n              {recallReadyToClose ? (\n                <ActionItem\n                  icon={<Play className="h-3.5 w-3.5" />}\n                  label={t(\n                    "catalogLifecycle.actions.closeRecall",\n                  )}\n                  hint={t(\n                    "catalogLifecycle.simple.actionHints.closeRecall",\n                  )}\n                  disabled={actionsDisabled}\n                  onClick={() =>\n                    onChooseCommand(\n                      "close-recall",\n                    )\n                  }\n                />\n              ) : (\n                <ActionItem\n                  icon={<ShieldCheck className="h-3.5 w-3.5" />}\n                  label={t(\n                    "catalogLifecycle.simple.manageConfirmedIssue",\n                  )}\n                  hint={t(\n                    "catalogLifecycle.simple.manageConfirmedIssueHint",\n                  )}\n                  disabled={actionsDisabled}\n                  onClick={onManageWholeProductIssue}\n                  emphasis="warning"\n                />\n              )}\n            </>\n          ) : null}\n'''
text = text[:start] + replacement + text[end:]

start = text.index("      {recallCompletionBlockers.length > 0 ? (")
end = text.index("\n      {pendingActionKey ? (", start)
replacement = '''      {showProblemRecovery && recallInventorySummary ? (\n        <div className="border-t border-slate-100 px-5 py-3">\n          <div className="flex flex-wrap items-center gap-2">\n            <p className="text-[10px] font-black text-slate-900">\n              {t("productQualityWorkspace.affectedStockTitle")}\n            </p>\n            <span className="rounded-full bg-slate-100 px-2 py-1 text-[9px] font-black text-slate-600">\n              {t("productQualityWorkspace.batchCount", {\n                count: recallInventorySummary.batch_count,\n              })}\n            </span>\n          </div>\n          {recallInventorySummary.locations_preview.length > 0 ? (\n            <div className="mt-2 flex flex-wrap gap-1.5">\n              {recallInventorySummary.locations_preview.map((location) => (\n                <span\n                  key={location.location_id}\n                  className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[9px] font-bold text-slate-700"\n                >\n                  {t("productQualityWorkspace.locationStock", {\n                    name: location.location_name,\n                    quantity: location.on_hand_quantity,\n                  })}\n                </span>\n              ))}\n              {recallInventorySummary.locations_truncated ? (\n                <span className="px-2 py-1.5 text-[9px] font-bold text-slate-500">\n                  {t("productQualityWorkspace.moreLocationsCompact")}\n                </span>\n              ) : null}\n            </div>\n          ) : null}\n        </div>\n      ) : null}\n'''
text = text[:start] + replacement + text[end:]
write(path, text)

# 3) Update focused acceptance tests: backend blocker evidence remains parsed, while the
# operator sees only compact stock context and the two-action journey.
path = "dashboard/src/test/products-lifecycle-guided-recovery.test.ts"
text = read(path)
text = replace_once(
    text,
    '    expect(panel).toContain("recallCompletionTitle");\n    expect(panel).toContain("recallBlockerActions.${item.code}");',
    '    expect(panel).toContain("productQualityWorkspace.affectedStockTitle");\n    expect(panel).toContain("productQualityWorkspace.locationStock");\n    expect(panel).toContain("recallReadyToClose ?");\n    expect(panel).not.toContain("recallBlockerActions.${item.code}");',
    "guided recovery assertions",
)
write(path, text)

path = "dashboard/src/test/products-enter-recall-ux.test.ts"
text = read(path)
old = '''    expect(panel).toContain(\n      "recallCompletionBlockers.length > 0",\n    );\n    expect(panel).toContain(\n      "catalogLifecycle.simple.recallCompletionTitle",\n    );\n    expect(panel).toContain(\n      "catalogLifecycle.simple.recallCompletionHint",\n    );\n    expect(panel).toContain(\n      "catalogLifecycle.blockers.",\n    );\n    expect(panel).toContain('item.code !== "INVENTORY_BALANCE"');\n    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');'''
new = '''    expect(panel).toContain(\n      "productQualityWorkspace.affectedStockTitle",\n    );\n    expect(panel).toContain(\n      "productQualityWorkspace.locationStock",\n    );\n    expect(panel).toContain(\n      "recallReadyToClose ?",\n    );\n    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');\n    expect(panel).not.toContain(\n      "catalogLifecycle.simple.recallCompletionTitle",\n    );\n    expect(panel).not.toContain(\n      "recallBlockerActions.${item.code}",\n    );'''
text = replace_once(text, old, new, "enter recall assertions")
write(path, text)

path = "dashboard/src/test/quality-safety-v1-closure.test.ts"
text = read(path)
old = '''    expect(panel).toContain('item.code !== "INVENTORY_BALANCE"');\n    expect(panel.match(/catalogLifecycle\\.simple\\.manageConfirmedIssue/g)?.length).toBe(2);'''
new = '''    expect(panel).toContain("recallReadyToClose ?");\n    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');\n    expect(panel).toContain("productQualityWorkspace.affectedStockTitle");\n    expect(panel).not.toContain('item.code !== "INVENTORY_BALANCE"');'''
text = replace_once(text, old, new, "quality closure two-action assertions")
text = replace_once(
    text,
    '    expect(workspace).toContain("productQualityWorkspace.configureDestinations");',
    '    expect(workspace).toContain("productQualityWorkspace.configureDestinations");\n    expect(workspace).toContain("needsDestinationSetup");\n    expect(workspace).not.toContain("ProductQualityReadiness");\n    expect(workspace).not.toContain("common.refresh");',
    "quality closure workspace assertions",
)
write(path, text)

# Reuse installed dependencies without reinstalling anything.
if not WORKTREE_NODE_MODULES.exists():
    run("cmd", "/c", "mklink", "/J", str(WORKTREE_NODE_MODULES), str(MAIN_NODE_MODULES))

run("git", "diff", "--check")
run(
    str(NODE),
    str(MAIN_NODE_MODULES / "vitest" / "vitest.mjs"),
    "run",
    "src/test/products-lifecycle-guided-recovery.test.ts",
    "src/test/products-enter-recall-ux.test.ts",
    "src/test/quality-safety-v1-closure.test.ts",
    "src/test/batch-focus-workspace.test.tsx",
    "src/test/catalog-inventory-boundary.test.ts",
    "src/test/products-status-summary.test.tsx",
    cwd=DASHBOARD,
)
run(str(NODE), str(MAIN_NODE_MODULES / "vite" / "bin" / "vite.js"), "build", cwd=DASHBOARD)
run("git", "diff", "--check")

run(
    "git", "add",
    "dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx",
    "dashboard/src/features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    "dashboard/src/test/products-lifecycle-guided-recovery.test.ts",
    "dashboard/src/test/products-enter-recall-ux.test.ts",
    "dashboard/src/test/quality-safety-v1-closure.test.ts",
)
run("git", "rm", "tools/_tmp_whole_product_quality_ux.py")
run("git", "commit", "-m", "ux(quality): make whole-product handling direct")
run("git", "push", "origin", f"HEAD:{BRANCH}")
run("git", "status", "--short")
run("git", "rev-parse", "HEAD")
