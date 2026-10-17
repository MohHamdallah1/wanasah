import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { formatInventoryInteger, formatWarehouseDeactivationBlocker } from "@/pages/inventory/warehouse-locations/i18n";
import { warehousePresentationCopy } from "@/pages/inventory/warehouse-locations/presentationI18n";
import { branchSelectorCopy } from "@/pages/inventory/warehouse-locations/branchSelectorI18n";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");
const warehouse = () => read("src/pages/inventory/TabWarehouseLocations.tsx");

describe("CP13 Warehouse setup final presentation", () => {
  it("keeps a compact warehouse-first management surface with explicit lifecycle state", () => {
    const source = warehouse();
    expect(source).toContain('data-cp13-density="compact"');
    expect(source).toContain("md:h-14");
    expect(source).toContain("location.is_active ? copy.active : copy.inactive");
    expect(source).toContain('openStateAction(location, "deactivate")');
    expect(source).toContain('openStateAction(location, "activate")');
    expect(source).toContain("disabled={!canAt(location.id, \"location.state\")}");
  });

  it("keeps create/edit focused on warehouse identity and the bounded V1 physical location profile", () => {
    const source = warehouse();
    expect(source).toContain("presentation.identityTitle");
    expect(source).toContain("presentation.locationTitle");
    expect(source).not.toContain("presentation.lifecycleTitle");
    expect(source).toContain("/warehouse/locations/code-suggestion");
    expect(source).toContain("copy.codeHint");
    expect(source).toContain("copy.address");
    expect(source).toContain("copy.locationLink");
    expect(source).toContain("copy.latitude");
    expect(source).toContain("copy.longitude");
    expect(source).not.toContain("presentation.locationHint");
    expect(source).not.toContain("presentation.identityHint");
    expect(source).not.toContain("copy.requiredFieldsPrefix");
    expect(source).not.toContain("copy.requiredFieldsSuffix");
    expect(source).toContain("copy.coordinatesHint");
    expect(source).toContain('type="submit"');
    expect(source).toContain("<form noValidate");
    expect(source).toContain("onSubmit={(event) => { event.preventDefault(); void handleSave(); }}");
    expect(source).not.toContain("ref={nameInputRef} required");
    expect(source).not.toContain("ref={codeInputRef} required");
    expect(source).not.toContain("required={formMode === \"create\"}");
    expect(source).toContain('t("inventoryWarehouses.errors.nameInvalid")');
    expect(source).toContain('t("inventoryWarehouses.errors.codeInvalid")');
    expect(source).toContain("copy.addressRequired");
    expect(source).toContain("aria-invalid={fieldIssue?.field === \"name\"}");
    expect(source).toContain("aria-invalid={fieldIssue?.field === \"code\"}");
    expect(source).toContain("requestAnimationFrame");
  });

  it("keeps Branch association dormant in the V1 Warehouse UX without deleting the backend relation", () => {
    const source = warehouse();
    expect(source).not.toContain('const canReadBranches = access.can("branch.read")');
    expect(source).not.toContain("<BranchSelector");
    expect(source).not.toContain("presentation.branchTitle");
    expect(source).not.toContain("mutationBody.branch_id");
    expect(source).toContain("branch_id: number | null");
    expect(source).not.toContain("BranchManagementModal");
    expect(source).not.toContain("copy.manageBranches");
    expect(source).not.toMatch(/isOwner|ownerOnly|role\s*===\s*["']owner/i);
  });

  it("preserves the dormant Branch selector contract for the later organization workflow", () => {
    const selector = read("src/pages/inventory/warehouse-locations/BranchSelector.tsx");
    const ar = branchSelectorCopy("ar");
    const en = branchSelectorCopy("en");
    expect(selector).toContain("preservedCurrent = !branch.is_active");
    expect(selector).toContain("disabled={preservedCurrent && value !== currentBranchId}");
    expect(selector).toContain("copy.inactiveCurrent");
    expect(selector).toContain("copy.active");
    expect(ar.assignmentRule).toContain("النشطة");
    expect(en.assignmentRule).toContain("active branches");
  });

  it("presents quality destinations as a dedicated warehouse setup view rather than a fixed daily stock action", () => {
    const source = warehouse();
    const quality = read("src/features/inventory/quality/QualityHandlingDestinationsCard.tsx");
    expect(source).toContain('type WarehouseSetupView = "warehouses" | "quality"');
    expect(source).toContain('access.can("inventory.transfer_policy.manage")');
    expect(source).toContain('setSetupView("quality")');
    expect(source).toContain('setSetupView("warehouses")');
    expect(source).toContain('data-warehouse-setup-view="quality"');
    expect(source.match(/<QualityHandlingDestinationsCard/g)?.length).toBe(1);
    expect(quality).toContain('data-warehouse-setup="quality-policy"');
    expect(quality).toContain("presentation.qualityPolicy");
    expect(quality).toContain("presentation.qualityPolicyHint");
    expect(quality).toContain("useTransferDestinationPolicy");
    expect(quality).not.toMatch(/quality.?staging/i);
  });

  it("keeps backend blocker authority and turns accepted blocker evidence into operator references", () => {
    const source = warehouse();
    expect(source).toContain('codeValue === "LOCATION_DEACTIVATION_BLOCKED"');
    expect(source).toContain("formatWarehouseDeactivationBlocker(context, language)");
    expect(source).toContain("presentation.deactivationNextStep");
    const issue = formatWarehouseDeactivationBlocker({ blocker_type: "OPEN_TRANSFER", reference_number: "TR-104" }, "en");
    expect(issue.title.toLowerCase()).toContain("transfer");
    expect(issue.details.join(" ")).toContain("TR-104");
  });

  it("keeps canonical capability gating for create, edit and state changes", () => {
    const source = warehouse();
    expect(source).toContain('access.can("location.create")');
    expect(source).toContain('canAt(location.id, "location.update")');
    expect(source).toContain('canAt(location.id, "location.state")');
    expect(source).toContain('access.can("inventory.minimum_stock.manage")');
    expect(source).not.toMatch(/admin|superuser/i);
  });

  it("has Arabic RTL and English LTR copy with Western-digit formatting", () => {
    const source = warehouse();
    const ar = warehousePresentationCopy("ar");
    const en = warehousePresentationCopy("en");
    expect(source).toContain("dir={dir}");
    expect(ar.identityTitle).toContain("المستودع");
    expect(en.identityTitle).toBe("Warehouse identity");
    expect(formatInventoryInteger(123456, "ar")).toMatch(/^[0-9,٬]+$/);
    expect(formatInventoryInteger(123456, "en")).toMatch(/^[0-9,]+$/);
  });

  it("keeps keyboard/focus hooks and one phone-width action surface explicit", () => {
    const source = warehouse();
    const modal = read("src/components/ui/modal.tsx");
    const focusTrap = read("src/hooks/useDialogFocusTrap.ts");
    expect(source).toContain("focus-visible:ring-2");
    expect(source).toContain("autoFocus");
    expect(source).toContain('data-cp13-phone-list="true"');
    expect(source).toContain("md:hidden");
    expect(source).toContain("overflow-x-auto");
    expect(source).toContain("md:min-w-[760px]");
    expect(modal).toContain("useDialogFocusTrap");
    expect(focusTrap).toContain('event.key === "Escape"');
    expect(focusTrap).toContain("restore.focus()");
  });

  it("shows concise loading, recoverable error/retry and separate setup copy in both languages", () => {
    const source = warehouse();
    expect(source).toContain('role="status"');
    expect(source).toContain("setLoadIssue(message)");
    expect(source).toContain("presentation.retry");
    expect(source).toContain("setRefreshKey((value) => value + 1)");
    expect(warehousePresentationCopy("ar").qualityPolicy).toBe("إعداد وسياسة");
    expect(warehousePresentationCopy("en").qualityPolicy).toBe("Setup / policy");
  });
});
