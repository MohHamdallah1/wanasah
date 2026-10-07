import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { webcrypto } from "node:crypto";
import type { ReactNode } from "react";
import i18n from "@/i18n";
import { resources } from "@/i18n/resources";
import { parseSupplier, parseSupplierPage } from "@/features/suppliers/contracts";
import { SupplierSelector } from "@/features/suppliers/SupplierSelector";
import { SupplierEditor } from "@/pages/suppliers/SupplierEditor";
import { SupplierTable } from "@/pages/suppliers/SupplierTable";
import SuppliersPage from "@/pages/suppliers/SuppliersPage";
import { useSupplierCommands } from "@/pages/suppliers/useSupplierCommands";
import { useInboundPosting } from "@/pages/inventory/inbound/useInboundPosting";
import { useProductQualityCommands } from "@/features/inventory/quality/useProductQualityCommands";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { getOrCreateDurableCommand, durableScope } from "@/lib/durableOperations";
import { useWholeProductQualityDraft } from "@/features/inventory/quality/useWholeProductQualityDraft";

const fake = vi.hoisted(() => ({ fetch: vi.fn(), read: true, manage: true, online: true }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/hooks/useNetworkStatus", () => ({ useNetworkStatus: () => fake.online }));
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  data: { company_id: 1, driver_id: 2 }, can: (code: string) => code === "supplier.read" ? fake.read : fake.manage,
  isPending: false,
}) }));

const row = { id: 3, name: "ABC Trading", code: "ABC", contact_person: "Contact", phone: "+962123", email: "a@example.com",
  address: null, notes: null, is_active: true, version: 1, created_at: "2026-10-07T08:00:00Z", updated_at: "2026-10-07T08:00:00Z" };
const page = { items: [row], next_cursor: null, has_more: false };
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(async () => {
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  localStorage.clear(); fake.fetch.mockReset(); fake.read = true; fake.manage = true; fake.online = true;
  fake.fetch.mockResolvedValue(page);
  await i18n.changeLanguage("en");
});
afterEach(cleanup);

describe("Supplier V1 contract and presentation", () => {
  it("rejects malformed, duplicate and unbounded responses", () => {
    expect(parseSupplier(row)).toEqual(row);
    expect(parseSupplierPage(page).items).toHaveLength(1);
    expect(() => parseSupplier({ ...row, is_active: "true" })).toThrow();
    expect(() => parseSupplierPage({ ...page, has_more: true })).toThrow();
    expect(() => parseSupplierPage({ ...page, items: [row, row] })).toThrow();
    expect(() => parseSupplierPage({ ...page, items: Array(101).fill(row) })).toThrow();
  });
  it("provides matching Arabic and English keys and locale-driven direction", async () => {
    const keys = (object: Record<string, unknown>, prefix = ""): string[] => Object.entries(object).flatMap(([key, value]) =>
      typeof value === "object" && value !== null ? keys(value as Record<string, unknown>, `${prefix}${key}.`) : `${prefix}${key}`);
    expect(keys(resources.ar.translation.suppliers).sort()).toEqual(keys(resources.en.translation.suppliers).sort());
    await i18n.changeLanguage("ar");
    render(<SupplierTable items={[row]} manage={false} disabled={false} onEdit={vi.fn()} onState={vi.fn()} />);
    expect(screen.getByText("نشط")).toBeInTheDocument(); expect(document.documentElement.dir).toBe("rtl");
    await act(() => i18n.changeLanguage("en")); expect(document.documentElement.dir).toBe("ltr");
  });
  it("denies the page and selector without read authority", () => {
    fake.read = false;
    render(<SuppliersPage />, { wrapper });
    expect(screen.getByRole("alert")).toHaveTextContent("permission");
    cleanup(); render(<SupplierSelector value={null} onChange={vi.fn()} />, { wrapper });
    expect(screen.getByRole("combobox")).toBeDisabled(); expect(fake.fetch).not.toHaveBeenCalled();
  });
  it("renders list, empty, failed and read-only states", async () => {
    fake.manage = false;
    const view = render(<SuppliersPage />, { wrapper });
    await screen.findByText("ABC Trading"); expect(screen.queryByRole("button", { name: "Add supplier" })).toBeNull();
    view.unmount(); fake.fetch.mockResolvedValue({ ...page, items: [] });
    const empty = render(<SuppliersPage />, { wrapper }); await screen.findByText(/No matching suppliers/); empty.unmount();
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "SUPPLIER_PERMISSION_DENIED", status: 403 }));
    render(<SuppliersPage />, { wrapper }); await screen.findByRole("alert");
  });
  it("selects only active server options and submits the authoritative ID", async () => {
    const select = vi.fn(); render(<SupplierSelector value={null} onChange={select} />, { wrapper });
    await screen.findByRole("option", { name: "ABC Trading · ABC" });
    expect(fake.fetch.mock.calls[0][0]).toContain("active=true"); expect(fake.fetch.mock.calls[0][0]).toContain("limit=30");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "3" } }); expect(select).toHaveBeenCalledWith(3);
  });
  it("shows an inactive restored selection without offering it for new selection", async () => {
    fake.fetch.mockImplementation((url: string) => Promise.resolve(url.startsWith("/suppliers?") ? { ...page, items: [] } : { ...row, is_active: false }));
    render(<SupplierSelector value={3} onChange={vi.fn()} />, { wrapper });
    await screen.findByText(/This supplier is inactive/);
    expect(screen.getByRole("option", { name: /ABC Trading/ })).toBeDisabled();
  });
  it("uses a semantic form, initial focus and scoped saved draft", async () => {
    const save = vi.fn().mockResolvedValue(true); const close = vi.fn();
    render(<SupplierEditor supplier={null} storageKey="supplier-draft:1:2" busy={false} blocked={false} onSave={save} onClose={close} />);
    const name = screen.getByRole("textbox", { name: "Supplier name" });
    await waitFor(() => expect(name).toHaveFocus());
    fireEvent.change(name, { target: { value: " New supplier " } });
    expect(localStorage.getItem("supplier-draft:1:2")).toContain("New supplier");
    fireEvent.submit(name.closest("form")!);
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ name: "New supplier" })));
    expect(close).toHaveBeenCalled(); expect(localStorage.getItem("supplier-draft:1:2")).toBeNull();
  });
});

describe("durable Supplier and Inbound commands", () => {
  it("keeps a 5xx outcome ambiguous even when it carries a known Supplier rejection code", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "SUPPLIER_INACTIVE", status: 500 }));
    const hook = renderHook(() => useSupplierCommands(1, 2), { wrapper });
    await act(async () => { expect(await hook.result.current.execute({ endpoint: "/suppliers", method: "POST", body: { name: "Unknown result" } })).toBe(false); });
    expect(hook.result.current.pending).not.toBeNull();
  });
  it("preserves an unsubmitted quality draft across refresh without crossing actor scope", () => {
    const hook = renderHook(() => useWholeProductQualityDraft(1, 2, 7));
    hook.result.current.save("RETURN_TO_VENDOR", { reason: "Edited reason", supplierId: 3 });
    hook.unmount();
    const resumed = renderHook(() => useWholeProductQualityDraft(1, 2, 7));
    expect(resumed.result.current.read("RETURN_TO_VENDOR")?.supplierId).toBe(3);
    const other = renderHook(() => useWholeProductQualityDraft(1, 4, 7));
    expect(other.result.current.read("RETURN_TO_VENDOR")).toBeNull();
  });
  it("preserves identity through lost response, refresh and changed-input attempts", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE" }));
    const first = renderHook(() => useSupplierCommands(1, 2), { wrapper });
    const command = { endpoint: "/suppliers", method: "POST" as const, body: { name: "New supplier" } };
    await act(async () => { expect(await first.result.current.execute(command)).toBe(false); });
    const sentId = JSON.parse(fake.fetch.mock.calls[0][1].body).request_id;
    first.unmount();
    const resumed = renderHook(() => useSupplierCommands(1, 2), { wrapper });
    await waitFor(() => expect(resumed.result.current.pending).not.toBeNull());
    const count = fake.fetch.mock.calls.length;
    await act(async () => { expect(await resumed.result.current.execute({ ...command, body: { name: "Different" } })).toBe(false); });
    expect(fake.fetch).toHaveBeenCalledTimes(count);
    fake.fetch.mockResolvedValue(row);
    await act(async () => { expect(await resumed.result.current.execute()).toBe(true); });
    expect(JSON.parse(fake.fetch.mock.calls.at(-1)![1].body).request_id).toBe(sentId);
    expect(resumed.result.current.pending).toBeNull();
  });
  it("never sends a Supplier administrative command while offline", async () => {
    fake.online = false; const hook = renderHook(() => useSupplierCommands(1, 2), { wrapper });
    await act(async () => { expect(await hook.result.current.execute({ endpoint: "/suppliers", method: "POST", body: { name: "Draft" } })).toBe(false); });
    expect(fake.fetch).not.toHaveBeenCalled();
  });
  it("replays an Inbound full payload after refresh with the same supplier and request ID", async () => {
    const payload = { supplier_id: 3, location_id: 5, reference_id: "INB", items: [] };
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE" }));
    const hook = renderHook(() => useInboundPosting({ companyId: 1, actorId: 2, locationId: 5, authenticatedFetch: fake.fetch }));
    await act(async () => { await expect(hook.result.current.post(payload)).rejects.toBeDefined(); });
    const sent = JSON.parse(fake.fetch.mock.calls[0][1].body); hook.unmount();
    const resumed = renderHook(() => useInboundPosting({ companyId: 1, actorId: 2, locationId: 5, authenticatedFetch: fake.fetch }));
    await waitFor(() => expect(resumed.result.current.pending).not.toBeNull());
    fake.fetch.mockResolvedValue({ message: "INBOUND_POSTED" });
    await act(async () => { expect(await resumed.result.current.post()).toBe(true); });
    expect(JSON.parse(fake.fetch.mock.calls.at(-1)![1].body)).toEqual(sent);
  });
  it("recovers previous Inbound storage without creating a new request identity", async () => {
    const requestId = "68c80f9b-041e-450f-92af-d2e4f341dbe8";
    const payload = { location_id: 5, reference_id: "LEGACY", items: [] };
    localStorage.setItem("legacy-id", requestId); localStorage.setItem("legacy-body", JSON.stringify(payload));
    fake.fetch.mockResolvedValue({ message: "INBOUND_POSTED" });
    const hook = renderHook(() => useInboundPosting({ companyId: 1, actorId: 2, locationId: 5, authenticatedFetch: fake.fetch,
      legacyRequestKey: "legacy-id", legacyPayloadKey: "legacy-body" }));
    await waitFor(() => expect(hook.result.current.pending).not.toBeNull());
    await act(async () => { expect(await hook.result.current.post()).toBe(true); });
    expect(JSON.parse(fake.fetch.mock.calls[0][1].body)).toEqual({ request_id: requestId, ...payload });
    expect(localStorage.getItem("legacy-id")).toBeNull();
  });
  it("retries whole-product return independently of current stock preview after a lost response", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE" }));
    const hook = renderHook(() => useProductQualityCommands({ productVariantId: 7, onSucceeded: vi.fn() }), { wrapper });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { expect(await hook.result.current.resolveAll({ action: "RETURN_TO_VENDOR", reason: "Issue", supplierId: 3, confirmationPassword: "first-credential", postResolutionHold: "SALES_HOLD" })).toBe(false); });
    const sent = JSON.parse(fake.fetch.mock.calls[0][1].body); expect(sent.supplier_id).toBe(3); expect(sent.recipient_name).toBeUndefined();
    expect(JSON.stringify(localStorage)).not.toContain("first-credential");
    expect(hook.result.current.pending?.command.payload).not.toHaveProperty("confirmation_password");
    hook.unmount();
    const resumed = renderHook(() => useProductQualityCommands({ productVariantId: 7, onSucceeded: vi.fn() }), { wrapper });
    await waitFor(() => expect(resumed.result.current.pending).not.toBeNull());
    fake.fetch.mockResolvedValue({ message: "Completed", action: "RETURN_TO_VENDOR", product_variant_id: 7, total_quantity: "4", location_count: 1, post_resolution_hold: "SALES_HOLD",
      locations: [{ location_id: 5, location_name: "Warehouse", quantity: "4" }] });
    await act(async () => { expect(await resumed.result.current.retryPending("")).toBe(false); });
    expect(fake.fetch).toHaveBeenCalledTimes(1);
    await act(async () => { expect(await resumed.result.current.retryPending("fresh-credential")).toBe(true); });
    expect(JSON.parse(fake.fetch.mock.calls.at(-1)![1].body)).toEqual({ ...sent, confirmation_password: "fresh-credential" });
    expect(JSON.stringify(localStorage)).not.toContain("fresh-credential");
  });
  it("replays a stored pre-Supplier quality command while the new UI exposes only selection", async () => {
    const old = await getOrCreateDurableCommand(durableScope(1, 2, "whole-product-quality-resolve-v2", "7:RETURN_TO_VENDOR"),
      { action: "RETURN_TO_VENDOR", reason: "Issue", recipient_name: "Legacy recipient" });
    fake.fetch.mockResolvedValue({ message: "Completed", action: "RETURN_TO_VENDOR", product_variant_id: 7, total_quantity: "4", location_count: 1, post_resolution_hold: "NONE",
      locations: [{ location_id: 5, location_name: "Warehouse", quantity: "4" }] });
    const hook = renderHook(() => useProductQualityCommands({ productVariantId: 7, onSucceeded: vi.fn() }), { wrapper });
    await waitFor(() => expect(hook.result.current.pending).not.toBeNull());
    await act(async () => { expect(await hook.result.current.retryPending("fresh-credential")).toBe(true); });
    expect(JSON.parse(fake.fetch.mock.calls[0][1].body).request_id).toBe(old.requestId);
    const source = readFileSync(resolve(process.cwd(), "src/features/inventory/quality/WholeProductQualityActionsPanel.tsx"), "utf8");
    const inbound = readFileSync(resolve(process.cwd(), "src/pages/inventory/Tab2Inbound.tsx"), "utf8");
    expect(source).toContain("<SupplierSelector"); expect(source).not.toContain("recipientName"); expect(inbound).toContain("<SupplierSelector");
  });
});
