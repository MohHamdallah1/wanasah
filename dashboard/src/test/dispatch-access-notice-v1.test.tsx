import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { DispatchAccessNotice } from "@/features/dispatch/DispatchAccessNotice";
import { useDispatchAccessGate } from "@/features/dispatch/useDispatchAccessGate";
import type { useInventoryAccess } from "@/hooks/useInventoryAccess";
import type { InventoryCapabilities } from "@/hooks/useInventoryAccess";

describe("Dispatch D09 fail-closed UI", () => {
  it("shows an Arabic permission denial without leaking prior shop, zone or financial rows", async () => {
    await setAppLanguage("ar");
    const retry = vi.fn();
    render(<DispatchAccessNotice state="denied" onRetry={retry} />);
    expect(screen.getByRole("alert").textContent).toContain("لا تملك صلاحية");
    expect(screen.getByRole("alert").textContent).not.toMatch(/اسم المحل|الرصيد|credit cap|private/i);
    fireEvent.click(screen.getByRole("button", { name: "إعادة المحاولة" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("shows distinct English pending and error states", async () => {
    await setAppLanguage("en");
    const { rerender } = render(<DispatchAccessNotice state="loading" />);
    expect(screen.getByRole("status").textContent).toContain("Checking access permissions");
    rerender(<DispatchAccessNotice state="error" />);
    expect(screen.getByRole("alert").textContent).toContain("Unable to verify access");
    expect(screen.getByRole("alert").textContent).toContain("Previously loaded data is hidden");
  });
});

const ownerAccess: InventoryCapabilities = {
  company_id: 4, principal_id: 19, backoffice_user_id: 20,
  is_company_owner: true, location_id: null,
  permissions: ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"],
  any_permissions: ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"],
  location_permissions: [],
};
type Access = ReturnType<typeof useInventoryAccess>;
const query = (overrides: Record<string, unknown> = {}): Access => ({
  data: ownerAccess, dataUpdatedAt: 100, isError: false, isFetching: false,
  isPending: false, refetch: vi.fn(), error: null, ...overrides,
} as unknown as Access);

describe("Dispatch D09 revocation, denial, and principal handoff gate", () => {
  it("hides already-authorized rows immediately on 403, then re-admits only refreshed server grants", () => {
    const access = query();
    const { result, rerender } = renderHook(({ value }: { value: Access }) => useDispatchAccessGate(value), {
      initialProps: { value: access },
    });
    expect(result.current.grants.routes).toBe(true);
    act(() => { window.dispatchEvent(new Event("inventory-permission-denied")); });
    expect(result.current.state).toBe("denied");
    expect(result.current.grants.routes).toBe(false);
    rerender({ value: query({ isFetching: true }) });
    expect(result.current.state).toBe("denied");
    rerender({ value: query({ data: {
      ...ownerAccess, principal_id: 22, is_company_owner: false,
      permissions: ["shortage.read"], any_permissions: ["shortage.read"],
    }, dataUpdatedAt: 101 }) });
    expect(result.current.state).toBe("ready");
    expect(result.current.grants.zones).toBe(false);
    expect(result.current.grants.shortages).toBe(true);
  });

  it("does not treat 401/403 or failed capability discovery as empty authorized data", () => {
    const failure = (status: number) => query({
      data: undefined, isError: true, error: Object.assign(new Error("denied"), { status }),
    });
    const { result, rerender } = renderHook(({ value }: { value: Access }) => useDispatchAccessGate(value), {
      initialProps: { value: failure(403) },
    });
    expect(result.current.state).toBe("denied");
    rerender({ value: failure(401) });
    expect(result.current.state).toBe("denied");
    rerender({ value: failure(500) });
    expect(result.current.state).toBe("error");
    rerender({ value: query({ isFetching: true }) });
    expect(result.current.state).toBe("loading");
  });
});
