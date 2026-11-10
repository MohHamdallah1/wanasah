import "@testing-library/jest-dom/vitest";
import { useState, type ComponentProps } from "react";
import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as XLSX from "xlsx";
import { setAppLanguage } from "@/i18n";
import { formatLocaleMoney } from "@/lib/localeNumbers";
import { ShopTable } from "@/components/dispatch/ShopTable";
import { ShopFormModal } from "@/components/dispatch/ShopFormModal";
import { ShortageModal } from "@/components/dispatch/ShortageModal";
import { ZoneModal } from "@/components/dispatch/ZoneModal";
import { ShopBulkImportModal } from "@/components/dispatch/ShopBulkImportModal";
import { beginDashboardSession, captureDashboardSession } from "@/lib/authStorage";
import type { Shop, Shortage, Zone } from "@/types/dispatch";

const mockTenant = vi.hoisted(() => ({ currency: "QAR" as string | null }));
vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: mockTenant.currency ? { company_id: 1, currency_code: mockTenant.currency } : undefined }),
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => vi.fn() }));
vi.mock("xlsx", async importOriginal => {
  const actual = await importOriginal<typeof import("xlsx")>();
  return { ...actual, writeFile: vi.fn() };
});
const zone: Zone = { id: "3", name: "Al Rayyan", scheduleStatus: "null",
  frequency: "", visitDay: "", startDate: "", intervalDays: null };
const shop: Shop = { id: "11", name: "Corner Shop", owner: "Amal",
  phone: "55511122", mapLink: "", zoneId: "3",
  initialDebt: 12.5, maxDebtLimit: 100, financeRedacted: false, sequence: 1, archived: false };
const shortage: Shortage = { id: "501", productId: "8", productName: "Lolo Chips", quantity: 3,
  status: "pending", zoneId: "3", zoneName: "Al Rayyan", shopId: "11",
  shopName: "Corner Shop", createdAt: "2026-11-09T12:00:00Z" };
const recovery: ComponentProps<typeof ShortageModal>["groupRecovery"] = {
  pending: null, blocked: false, restoring: false, busy: false,
  feedback: null, httpReference: null, onRetry: vi.fn(),
};
function shortageProps(): ComponentProps<typeof ShortageModal> {
  return {
    canCreate: true, canEdit: true, canCancel: true, isOpen: true, onClose: vi.fn(),
    zones: [zone], activeShops: [shop], shortageZoneId: "3", shortageShopId: "11",
    onZoneChange: vi.fn(), onShopChange: vi.fn(), productScope: null,
    newShortage: { quantity: 2, productId: "8", productName: "Lolo Chips" },
    onNewShortageChange: vi.fn(),
    shortageDraft: [{ productId: "8", productName: "Lolo Chips", quantity: 2 }],
    onAddProductToDraft: vi.fn(), onRemoveProductFromDraft: vi.fn(),
    onUpdateDraftQty: vi.fn(), onClearDraft: vi.fn(), onConfirmShortages: vi.fn(),
    shortages: [shortage], onDeleteShortage: vi.fn(), onDeleteShortageGroup: vi.fn(),
    onEditShortageGroup: vi.fn(), editingShortageIds: [], onCancelEdit: vi.fn(),
    drivers: [], shortageDriverId: "", onDriverChange: vi.fn(), groupRecovery: recovery,
  };
}
function createSession() {
  beginDashboardSession();
  localStorage.setItem("admin_token", "test");
  localStorage.setItem("refresh_token", "test");
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "11");
  localStorage.setItem("backoffice_user_id", "110");
  return captureDashboardSession()!;
}
beforeEach(async () => {
  mockTenant.currency = "QAR";
  vi.stubGlobal("crypto", webcrypto);
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
  await setAppLanguage("ar");
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); localStorage.clear(); });

describe("D13 real bilingual, currency, focus and shortage controls", () => {
  it("AR 390px Shop table has accessible edit/archive/select and never displays hardcoded JOD", () => {
    const edit = vi.fn(), archive = vi.fn();
    const props: ComponentProps<typeof ShopTable> = {
      shops: [shop], zones: [zone], isEditMode: true, isSaving: false,
      language: "ar", selectedShopIds: [], allFilteredShops: null,
      selectedZoneIdForZones: "3", onToggleSelectAll: vi.fn(), onToggleSelectShop: vi.fn(),
      onSequenceChange: vi.fn(), onEditShop: edit, onArchiveShop: archive,
      onDragStart: vi.fn(), onDrop: vi.fn(),
    };
    const view = render(<ShopTable {...props}/>);
    expect(screen.getByRole("checkbox", { name: "تحديد محل Corner Shop" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "تعديل بيانات Corner Shop" }));
    fireEvent.click(screen.getByRole("button", { name: "أرشفة محل Corner Shop" }));
    expect(edit).toHaveBeenCalledWith(shop);
    expect(archive).toHaveBeenCalledWith("11");
    expect(screen.getByText(formatLocaleMoney("12.5", "QAR", "ar"))).toBeInTheDocument();
    expect(view.container.textContent).not.toContain("د.أ");
    mockTenant.currency = "OMR";
    view.rerender(<ShopTable {...props} />);
    expect(screen.getByText(formatLocaleMoney("12.5", "OMR", "ar"))).toBeInTheDocument();
    mockTenant.currency = null;
    view.rerender(<ShopTable {...props} />);
    expect(screen.getByText("عملة الشركة غير متاحة حالياً")).toBeInTheDocument();
    expect(view.container.textContent).not.toContain("د.أ");
  });

  it("EN desktop Shop finance uses verified currency and never changes financial authority", async () => {
    await setAppLanguage("en");
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
    mockTenant.currency = "OMR";
    const save = vi.fn();
    render(<ShopFormModal isOpen onClose={vi.fn()} editingShopId="11"
      shopForm={{ name: shop.name, owner: shop.owner, phone: shop.phone, mapLink: "",
        zoneId: "3", initialDebt: "999", maxDebtLimit: "999" }}
      onShopFormChange={vi.fn()} zones={[zone]} onSave={save} onVerify={vi.fn()}
      onLeaveUncertain={vi.fn()} needsManualReconciliation={false}
      restoring={false} recoveryUnreadable={false} localTrackingId={null}
      serverReference={null} language="en" saving={false} needsVerification={false}
      canViewFinances finance={{ initialDebt: "12.500", maxDebtLimit: "100.000" }}
      financeLoading={false} feedback={null} />);
    expect(screen.getByTestId("shop-current-debt")).toHaveTextContent(formatLocaleMoney("12.500", "OMR", "en"));
    expect(screen.getByText("Company currency: OMR")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Shop name" })).toHaveFocus());
    expect(screen.queryByRole("textbox", { name: "Opening receivable" })).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("Zone dialog switches AR/EN labels, Enter submit and Escape cancellation with restored focus", async () => {
    await setAppLanguage("en");
    const save = vi.fn();
    function ZoneCase() {
      const [isOpen, setOpen] = useState(false);
      const [name, setName] = useState("");
      return <>
        <button type="button" onClick={() => setOpen(true)}>Open zone</button>
        <ZoneModal isOpen={isOpen} onClose={() => setOpen(false)} editingZoneId={null}
          zoneFormName={name} onZoneFormNameChange={setName} onSave={save}/>
      </>;
    }
    render(<ZoneCase />);
    const trigger = screen.getByRole("button", { name: "Open zone" });
    trigger.focus(); // A real keyboard/mouse activation starts from the triggering control.
    fireEvent.click(trigger);
    const name = screen.getByRole("textbox", { name: "Zone name" });
    await waitFor(() => expect(name).toHaveFocus());
    fireEvent.change(name, { target: { value: "West Zone" } });
    fireEvent.submit(name.closest("form")!);
    expect(save).toHaveBeenCalledOnce();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    await setAppLanguage("ar");
    fireEvent.click(trigger);
    expect(screen.getByRole("textbox", { name: "اسم المنطقة" })).toBeInTheDocument();
  });

  it("AR shortage draft and grouped Delete One / Delete All require keyboard-reachable confirmation", async () => {
    const props = shortageProps();
    render(<ShortageModal {...props}/>);
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "كمية المنتج المطلوب" })).toHaveFocus());
    const plus = screen.getByRole("button", { name: "زيادة كمية Lolo Chips" });
    fireEvent.click(plus);
    expect(props.onUpdateDraftQty).toHaveBeenCalledWith(0, 3);
    const open = screen.getByRole("button", { name: "عرض منتجات Corner Shop" });
    open.focus(); fireEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    const removeOne = screen.getByRole("button", { name: "حذف Lolo Chips من طلبات Corner Shop" });
    fireEvent.click(removeOne);
    expect(props.onDeleteShortage).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "نعم، حذف" })).toHaveFocus());
    fireEvent.keyDown(screen.getByRole("group", { name: "تأكيد الحذف" }), { key: "Escape" });
    expect(props.onDeleteShortage).not.toHaveBeenCalled();
    fireEvent.click(removeOne);
    fireEvent.click(screen.getByRole("button", { name: "نعم، حذف" }));
    expect(props.onDeleteShortage).toHaveBeenCalledExactlyOnceWith("501");
    const removeAll = screen.getByRole("button", { name: "حذف كل طلبات Corner Shop" });
    fireEvent.click(removeAll);
    expect(props.onDeleteShortageGroup).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "نعم، حذف" }));
    expect(props.onDeleteShortageGroup).toHaveBeenCalledWith(["501"]);
  });

  it("EN 390px shortage group is a labelled button, not a mouse-only clickable card", async () => {
    await setAppLanguage("en");
    const props = shortageProps();
    render(<ShortageModal {...props} canCreate={false} />);
    const open = screen.getByRole("button", { name: "Show items for Corner Shop" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Delete Lolo Chips from Corner Shop requests" })).toBeInTheDocument();
    expect(screen.getByText("Pending requests")).toBeInTheDocument();
  });

  it("EN shop import exposes correct template and keeps financial upload gated without currency", async () => {
    await setAppLanguage("en");
    const session = createSession();
    const view = render(<ShopBulkImportModal isOpen actorScope="1:11:110" session={session}
      onClose={vi.fn()} zones={[zone]} existingShops={[]} />);
    expect(screen.getByRole("dialog", { name: "Import shops" }).closest("[dir]")).toHaveAttribute("dir", "ltr");
    fireEvent.click(screen.getByRole("button", { name: "Download template" }));
    expect(XLSX.writeFile).toHaveBeenCalled();
    const workbook = vi.mocked(XLSX.writeFile).mock.calls[0]?.[0];
    const sheet = workbook && workbook.Sheets[workbook.SheetNames[0]];
    const rows = sheet ? XLSX.utils.sheet_to_json<string[]>(sheet, { header: 1 }) : [];
    expect(rows[0]?.[0]).toBe("Shop name (required)");
    mockTenant.currency = null;
    view.rerender(<ShopBulkImportModal isOpen actorScope="1:11:110" session={session}
      onClose={vi.fn()} zones={[zone]} existingShops={[]} />);
    expect(screen.getByText("Upload Excel or CSV file")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose file" })).toBeInTheDocument();
  });
});
