import "@testing-library/jest-dom/vitest";
import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { ShopBulkImportModal } from "@/components/dispatch/ShopBulkImportModal";
import { beginDashboardSession, captureDashboardSession } from "@/lib/authStorage";
import type { Zone } from "@/types/dispatch";

vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => vi.fn() }));
const zone = [{ id: "3", name: "Zone", shopsCount: 0, scheduleStatus: "null", startDate: "", intervalDays: null }] as Zone[];
const actorDraftKey = (scope: string) => `wanasah:dispatch:shop-import:v2:${scope}`;
const draft = (scope: string, shopName = "Actor Private Shop") => JSON.stringify({
  actorScope: scope, zoneId: "3", data: [{
    _id: "row-1", name: shopName, phone: "5551234567", mapLink: "",
    owner: "Owner Private", initialDebt: "0",
  }],
});
function login(company: string, principal: string, backoffice: string) {
  beginDashboardSession();
  localStorage.setItem("admin_token", "synthetic");
  localStorage.setItem("refresh_token", "synthetic-refresh");
  localStorage.setItem("company_id", company);
  localStorage.setItem("principal_id", principal);
  localStorage.setItem("backoffice_user_id", backoffice);
  return captureDashboardSession();
}
describe("D10 real Shop import modal principal-scope", () => {
  beforeEach(async () => {
    vi.stubGlobal("crypto", webcrypto);
    localStorage.clear();
    await setAppLanguage("ar");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

  it("restores a valid same-principal draft on refresh without loading a legacy company-wide draft", async () => {
    const session = login("1", "11", "110");
    const scope = "1:11:110";
    localStorage.setItem(actorDraftKey(scope), draft(scope));
    localStorage.setItem("shop_import_draft", JSON.stringify({
      companyId: "1", zoneId: "3", data: [{ name: "Old Tenant Leak", owner: "Unknown" }],
    }));
    render(<ShopBulkImportModal isOpen actorScope={scope} session={session}
      zones={zone} existingShops={[]} onClose={vi.fn()} />);
    expect(await screen.findByText("يوجد مسودة غير محفوظة!")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /استعادة المسودة/ }));
    expect(screen.getByDisplayValue("Actor Private Shop")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Old Tenant Leak");
    expect(localStorage.getItem(actorDraftKey(scope))).not.toBeNull();
  });

  it("B principal and different company never see or erase A's import draft, even with matching Zone ID", async () => {
    login("1", "11", "110");
    const aScope = "1:11:110", bScope = "1:22:220", cScope = "2:11:110";
    localStorage.setItem(actorDraftKey(aScope), draft(aScope, "A-Sensitive Shop"));
    let session = login("1", "22", "220");
    const view = render(<ShopBulkImportModal isOpen actorScope={bScope} session={session}
      zones={zone} existingShops={[]} onClose={vi.fn()} />);
    expect(screen.queryByText("يوجد مسودة غير محفوظة!")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("A-Sensitive Shop");
    session = login("2", "11", "110");
    view.rerender(<ShopBulkImportModal isOpen actorScope={cScope} session={session}
      zones={zone} existingShops={[]} onClose={vi.fn()} />);
    expect(screen.queryByText("يوجد مسودة غير محفوظة!")).not.toBeInTheDocument();
    expect(localStorage.getItem(actorDraftKey(aScope))).toBe(draft(aScope, "A-Sensitive Shop"));
  });

  it("a revoked modal discards the old private grid but leaves the same-user saved draft", async () => {
    const session = login("1", "11", "110"), scope = "1:11:110";
    localStorage.setItem(actorDraftKey(scope), draft(scope, "A-Only Grid"));
    const view = render(<ShopBulkImportModal isOpen actorScope={scope} session={session}
      zones={zone} existingShops={[]} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /استعادة المسودة/ }));
    expect(screen.getByDisplayValue("A-Only Grid")).toBeInTheDocument();
    act(() => view.rerender(<ShopBulkImportModal isOpen={false} actorScope={scope} session={session}
      zones={zone} existingShops={[]} onClose={vi.fn()} />));
    expect(screen.queryByDisplayValue("A-Only Grid")).not.toBeInTheDocument();
    expect(localStorage.getItem(actorDraftKey(scope))).not.toBeNull();
  });
});
