import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import i18n from "@/i18n";
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), permissions: new Set<string>() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({ can: (code: string) => mocks.permissions.has(code), canAny: (code: string) => mocks.permissions.has(code) }),
  useLocationCapabilities: () => (_locationId: number, code: string) => mocks.permissions.has(code),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
import { useTransferList } from "./hooks/useTransferList";
import { useTransferCommand } from "./hooks/useTransferCommand";
import { useTransferCreate } from "./hooks/useTransferCreate";
import { formatDate, formatTransferDateOnly } from "./utils";
import { formatTransferNumber } from "./i18n";
import { TransferDecisionModal } from "./TransferDecisionModal";
import { TransferTable } from "./TransferTable";
import { FefoOverrideEditor } from "./FefoOverrideEditor";
import { parseTransferPage } from "./parsers";
import { readTransferDraft, writeTransferDraft } from "./draftStorage";
import { transferCommandScope } from "./hooks/useTransferCommand";

const transfer = (id = 1, location = 11) => ({ id, reference_number: "TRN-" + id, source_location_id: location, source_location_name: "A1",
  destination_location_id: 12, destination_location_name: "A2", transfer_purpose: "WAREHOUSE_BALANCING" as const, status: "IN_TRANSIT" as const,
  dispatched_by: 81, dispatched_by_name: "Sender", received_by: null, received_by_name: null, cancelled_by: null, cancelled_by_name: null,
  line_count: 1, total_quantity: "4", notes: null, decision_reason: null, created_at: "2026-10-16T10:00:00Z", updated_at: "2026-10-16T10:00:00Z",
  accepted_at: null, rejected_at: null, cancelled_at: null, posted_at: null });
const page = (items = [transfer()], next: string | null = null) => ({ items, total: 2, has_more: Boolean(next), next_cursor: next });
beforeEach(async () => {
  localStorage.clear(); localStorage.setItem("company_id", "1"); localStorage.setItem("principal_id", "91");
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  mocks.fetch.mockReset(); mocks.permissions = new Set(["transfer.send", "transfer.destination", "inventory.fefo_override"]);
  await i18n.changeLanguage("en");
});
afterEach(cleanup);

it("retains loaded rows when infinite-scroll continuation fails and retries the same cursor", async () => {
  mocks.fetch
    .mockResolvedValueOnce(page([transfer()], "NEXT"))
    .mockRejectedValueOnce(Object.assign(new Error(), { status: 503 }))
    .mockResolvedValueOnce(page([transfer(2)]))
    .mockRejectedValueOnce(Object.assign(new Error(), { status: 503 }));
  const { result } = renderHook(() => useTransferList());
  await waitFor(() => expect(result.current.items).toHaveLength(1));
  act(() => result.current.loadMore());
  await waitFor(() => expect(result.current.failure?.phase).toBe("continuation"));
  expect(result.current.items.map((row) => row.id)).toEqual([1]);
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([1, 2]));
  const continuationUrls = mocks.fetch.mock.calls.map(([url]) => url).filter((url) => url.includes("cursor=NEXT"));
  expect(continuationUrls).toHaveLength(2);
  act(() => result.current.refreshTransfers());
  await waitFor(() => expect(result.current.failure?.phase).toBe("refresh"));
  expect(result.current.items.map((row) => row.id)).toEqual([1, 2]);
});

it("lists the authorized transfer workspace without hidden warehouse or direction parameters", async () => {
  mocks.fetch.mockResolvedValueOnce(page([transfer()]));
  const { result } = renderHook(() => useTransferList());
  await waitFor(() => expect(result.current.items).toHaveLength(1));
  const url = new URL(mocks.fetch.mock.calls[0][0], "http://test");
  expect(url.searchParams.has("location_id")).toBe(false);
  expect(url.searchParams.has("direction")).toBe(false);
  expect(url.searchParams.get("limit")).toBe("50");
});
it("persists ambiguous command through remount, rejects changed input, and retries only explicitly", async () => {
  const wire = { path: "/warehouse/unified/transfer/dispatch", method: "POST" as const, body: { source_location_id: 11, notes: "draft" } };
  mocks.fetch.mockRejectedValueOnce(Object.assign(new Error(), { status: 0, code: "NETWORK_UNAVAILABLE" }));
  const first = renderHook(() => useTransferCommand("TEST", 11));
  await act(async () => { await expect(first.result.current.execute(wire)).rejects.toBeTruthy(); });
  const id = JSON.parse(mocks.fetch.mock.calls[0][1].body).request_id;
  first.unmount();
  const second = renderHook(() => useTransferCommand("TEST", 11));
  await waitFor(() => expect(second.result.current.pending?.requestId).toBe(id));
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
  await act(async () => { await expect(second.result.current.execute({ ...wire, body: { notes: "changed" } })).rejects.toMatchObject({ code: "DURABLE_OPERATION_PENDING" }); });
  mocks.fetch.mockResolvedValueOnce({ message: "ok" });
  await act(async () => { await second.result.current.execute(); });
  expect(JSON.parse(mocks.fetch.mock.calls[1][1].body).request_id).toBe(id);
  expect(second.result.current.pending).toBeNull();
  mocks.fetch.mockResolvedValueOnce({ message: "ok" });
  await act(async () => { await second.result.current.execute(wire); });
  expect(JSON.parse(mocks.fetch.mock.calls[2][1].body).request_id).not.toBe(id);
});
it("keeps valid versioned drafts actor-partitioned and discards legacy replenishment drafts", () => {
  const scope = transferCommandScope("TRANSFER_DRAFT", 11);
  writeTransferDraft(scope, { schema_version: 2, source: null, destination: null, notes: "Keep", items: [] });
  expect(readTransferDraft(scope)?.notes).toBe("Keep");
  localStorage.setItem("company_id", "2");
  expect(readTransferDraft(transferCommandScope("TRANSFER_DRAFT", 11))).toBeNull();
});
it.each(["ar", "en"])("provides translated form submission, locale direction, Escape and focus restoration (%s)", async language => {
  await i18n.changeLanguage(language);
  const submit = vi.fn(); const close = vi.fn();
  const opener = document.createElement("button"); document.body.append(opener); opener.focus();
  render(<TransferDecisionModal action="receive" transfer={transfer()} decisionReason="" submitting={false} onClose={close} onDecisionReasonChange={vi.fn()} onSubmit={submit} />);
  const dialog = await screen.findByRole("dialog");
  expect(dialog.closest("[dir]")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
  fireEvent.submit(dialog.querySelector("form")!); expect(submit).toHaveBeenCalledOnce();
  fireEvent.keyDown(document, { key: "Escape" }); expect(close).toHaveBeenCalled();
  cleanup(); await waitFor(() => expect(document.activeElement).toBe(opener)); opener.remove();
});
it("hides manual batch selection without its exact capability and rejects malformed purpose contracts", () => {
  const item = { id: 1, product_variant_id: 1, draft_key: "K", name: "Product", sku: null, base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "Each",
    display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each", display_factor_to_base: "1", display_quantity_scale: 0,
    quantity_scale: 0, quantity_step: "1", available_quantity: "10", quantity: "1", fefo_mode: "override" as const, override_batch_id: null, override_reason_id: null, override_batch_available: null };
  render(<FefoOverrideEditor canOverride={false} item={item} draftItems={[item]} options={undefined} loading={false} onModeChange={vi.fn()} onBatchChange={vi.fn()} onReasonChange={vi.fn()} onAddBatchLine={vi.fn()} />);
  expect(screen.queryByText(i18n.t("inventoryTransfers.specificBatchHint"))).toBeNull();
  expect(screen.queryByRole("combobox", { name: i18n.t("inventoryTransfers.selectedBatch") })).toBeNull();
  expect(() => parseTransferPage(page([{ ...transfer(), transfer_purpose: undefined } as never]))).toThrow();
});

it.each(["ar", "en"])("formats western digits without duplicating locale extensions (%s)", async language => {
  await i18n.changeLanguage(language);
  expect(formatDate("2026-10-16T10:00:00Z")).not.toMatch(/[٠-٩]/);
  expect(formatTransferDateOnly("2026-10-16")).not.toMatch(/[٠-٩]/);
  expect(formatTransferNumber("2.5")).toMatch(/2/);
});

it("preserves full decimal display precision", () => {
  expect(formatTransferNumber("999999999999.999999")).toBe("999,999,999,999.999999");
});
it("clears busy state and pending state when the visible command scope changes during a request", async () => {
  let resolveOld!: (value: unknown) => void;
  mocks.fetch.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
  const { result, rerender } = renderHook(({ location }) => useTransferCommand("SCOPE", location), { initialProps: { location: 11 } });
  let request!: Promise<unknown>;
  act(() => { request = result.current.execute({ path: "/warehouse/unified/transfer/dispatch", method: "POST", body: { source_location_id: 11 } }); });
  await waitFor(() => expect(result.current.busy).toBe(true));
  rerender({ location: 22 });
  await waitFor(() => expect(result.current.busy).toBe(false));
  await act(async () => { resolveOld({ message: "ok" }); await request; });
  expect(result.current.pending).toBeNull(); expect(result.current.busy).toBe(false);
});

it("keeps table and phone presentation aligned without pagination controls", () => {
  render(<TransferTable items={[transfer()]} loading={false} loadingMore={false} hasMore={true}
    onLoadMore={vi.fn()} onOpenDetail={vi.fn()} onOpenAction={vi.fn()} />);
  expect(screen.getByRole("table").className).toContain("md:table");
  expect(screen.queryByRole("button", { name: "Previous page" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
  expect(document.querySelector("[data-transfer-scroll-sentinel='true']")).toBeTruthy();
});
it("keeps Tab and Shift+Tab within the decision dialog until it closes", async () => {
  render(<TransferDecisionModal action="cancel" transfer={transfer()} decisionReason="Reason" submitting={false} onClose={vi.fn()} onDecisionReasonChange={vi.fn()} onSubmit={vi.fn()} />);
  const dialog = screen.getByRole("dialog");
  const controls = dialog.querySelectorAll<HTMLElement>("button, textarea");
  await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  controls[controls.length - 1].focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(document.activeElement).toBe(controls[0]);
  controls[0].focus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(controls[controls.length - 1]);
});

it("reloads backend FEFO options when a persisted override draft is reopened", async () => {
  const product = { id: 100, product_variant_id: 100, draft_key: "saved-line", name: "Product", sku: null, base_uom_id: 1,
    base_uom_code: "EACH", base_uom_name: "Each", display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each",
    display_factor_to_base: "1", display_quantity_scale: 0, quantity_scale: 0, quantity_step: "1", available_quantity: "10",
    quantity: "2", fefo_mode: "override" as const, override_batch_id: 8, override_reason_id: 9, override_batch_available: "10" };
  const location = { id: 12, name: "A2", code: "A2", location_type: "WAREHOUSE" as const, vehicle_id: null };
  writeTransferDraft(transferCommandScope("TRANSFER_DRAFT", "workspace"), { schema_version: 2, source: { ...location, id: 11, code: "A1" }, destination: location, notes: "saved", items: [product] });
  mocks.fetch.mockImplementation(async (url: string) => url.includes("override-options") ? { location_id: 11, product_variant_id: 100, fefo_batch_id: 8,
    batches: [{ id: 8, batch_number: "LOT", production_date: null, expiry_date: null, available_quantity: "10", is_fefo_head: true }],
    reasons: [{ id: 9, code: "APPROVED", description: "Approved" }] } : url.includes("/locations?") ? new URL(url, "http://test").searchParams.get("purpose") === "source" ? [{ ...location, id: 11, code: "A1" }] : [location] :
    { items: [product], has_more: false, next_cursor: null, total: 1 });
  const { result } = renderHook(() => useTransferCreate({ onCompleted: vi.fn(), onInventoryChanged: vi.fn() }));
  act(() => result.current.openCreate());
  await waitFor(() => expect(result.current.overrideOptionsByProduct[100]?.batches).toHaveLength(1));
  act(() => result.current.closeCreate());
  act(() => result.current.openCreate());
  await waitFor(() => expect(result.current.overrideOptionsByProduct[100]?.batches).toHaveLength(1));
  expect(result.current.draftItems[0].override_batch_id).toBe(8);
});
