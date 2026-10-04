import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resources } from "@/i18n/resources";
import { BatchQuantityActions } from "@/pages/inventory/batches/BatchQuantityActions";
import { parseBatchStockSources } from "@/pages/inventory/batches/batchStockSourcesContract";
import { batchFocusPayload, batchSource } from "./fixtures/batchFocus";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), success: vi.fn(), error: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("@/hooks/useNetworkStatus", () => ({ useNetworkStatus: () => true }));
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  data: { company_id: 1, driver_id: 7 }, isCompanyAdmin: true, can: () => true,
}) }));
vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }));

beforeEach(() => { mocks.fetch.mockReset(); mocks.success.mockReset(); mocks.error.mockReset(); localStorage.clear(); });
afterEach(cleanup);

async function i18nInstance(language: "ar" | "en" = "en") {
  const i18n = createInstance();
  await i18n.init({ resources, lng: language, fallbackLng: "en", interpolation: { escapeValue: false } });
  return i18n;
}

function terminalPayload(action: "CONFIRM_DISPOSAL" | "CONFIRM_VENDOR_HANDOVER", allowed = true) {
  const source = batchSource(11, action === "CONFIRM_DISPOSAL" ? "Disposal area" : "Supplier return staging");
  const status = source.statuses[0];
  status.stock_status = action === "CONFIRM_DISPOSAL" ? "DISPOSAL_PENDING" : "QUARANTINED";
  status.on_hand_quantity = "8";
  status.reserved_quantity = "0";
  status.movable_quantity = "8";
  status.allowed_purposes = [];
  status.special_actions = status.special_actions.map((item) => ({ ...item, allowed: false, eligible_quantity: "0", reason_code: "STATE_RESTRICTION" }));
  status.reservation_evidence = { coverage: "NONE", reason: null, unattributed_quantity: "0", owners_truncated: false, owners: [] };
  status.terminal_actions = [
    { action: "CONFIRM_DISPOSAL", allowed: action === "CONFIRM_DISPOSAL" && allowed, eligible_quantity: action === "CONFIRM_DISPOSAL" && allowed ? "8" : "0", reason_code: action === "CONFIRM_DISPOSAL" && allowed ? "ALLOWED" : "STATE_RESTRICTION" },
    { action: "CONFIRM_VENDOR_HANDOVER", allowed: action === "CONFIRM_VENDOR_HANDOVER" && allowed, eligible_quantity: action === "CONFIRM_VENDOR_HANDOVER" && allowed ? "8" : "0", reason_code: action === "CONFIRM_VENDOR_HANDOVER" && allowed ? "ALLOWED" : "STATE_RESTRICTION" },
  ];
  return parseBatchStockSources(batchFocusPayload([source]));
}

async function mount(data: ReturnType<typeof terminalPayload>, language: "ar" | "en" = "en") {
  const i18n = await i18nInstance(language);
  const onChanged = vi.fn();
  const onRefresh = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><I18nextProvider i18n={i18n}><BatchQuantityActions
    batch={data.batch} productVariantId={data.product_variant_id} baseUomCode={data.base_uom_code}
    stockSources={data} onRefreshStockSources={onRefresh} onChanged={onChanged}
    onOpenTransfers={vi.fn()} onOpenReservationOwner={vi.fn()} />
  </I18nextProvider></QueryClientProvider>);
  return { i18n, onChanged, onRefresh };
}

describe("terminal inventory actions", () => {
  it("confirms physical disposal through the terminal backend command", async () => {
    const data = terminalPayload("CONFIRM_DISPOSAL");
    mocks.fetch.mockResolvedValue({
      message: "ok", movement_ids: [501], product_variant_id: 118, batch_id: 41, source_location_id: 11,
      disposed_quantity: "8", remaining_quantity: "0", origin_transfer_header_ids: [71], event_type: "INVENTORY_FINAL_DISPOSAL_CONFIRMED",
    });
    const { i18n, onChanged, onRefresh } = await mount(data);
    fireEvent.click(screen.getByRole("button", { name: i18n.t("terminalQualityActions.actions.CONFIRM_DISPOSAL.label") }));
    expect(screen.getByDisplayValue("8")).toHaveValue("8");
    fireEvent.change(screen.getByLabelText(i18n.t("terminalQualityActions.disposalReason")), { target: { value: "Destroyed after failed inspection" } });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("terminalQualityActions.confirm") }));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledOnce());
    const [url, init] = mocks.fetch.mock.calls[0];
    const body = JSON.parse(String(init.body));
    expect(url).toBe("/warehouse/quality/disposal/confirm");
    expect(init.method).toBe("POST");
    expect(body).toMatchObject({ source_location_id: 11, product_variant_id: 118, batch_id: 41, quantity: "8", reason: "Destroyed after failed inspection" });
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/i);
    await waitFor(() => expect(onRefresh).toHaveBeenCalledOnce());
    expect(onChanged).toHaveBeenCalledOnce();
    expect(mocks.error).not.toHaveBeenCalled();
  });

  it("confirms supplier handover only with the required human evidence", async () => {
    const data = terminalPayload("CONFIRM_VENDOR_HANDOVER");
    mocks.fetch.mockResolvedValue({
      message: "ok", movement_ids: [601], product_variant_id: 118, batch_id: 41, source_location_id: 11, source_status: "QUARANTINED",
      handed_over_quantity: "8", remaining_quantity: "0", origin_transfer_header_ids: [81], vendor_name: "Supplier One",
      vendor_reference: "V-44", handover_reference: "H-55", event_type: "INVENTORY_VENDOR_HANDOVER_CONFIRMED",
    });
    const { i18n } = await mount(data);
    fireEvent.click(screen.getByRole("button", { name: i18n.t("terminalQualityActions.actions.CONFIRM_VENDOR_HANDOVER.label") }));
    const confirm = screen.getByRole("button", { name: i18n.t("terminalQualityActions.confirm") });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(i18n.t("terminalQualityActions.vendorName")), { target: { value: "Supplier One" } });
    fireEvent.change(screen.getByLabelText(i18n.t("terminalQualityActions.vendorReference")), { target: { value: "V-44" } });
    fireEvent.change(screen.getByLabelText(i18n.t("terminalQualityActions.handoverReference")), { target: { value: "H-55" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledOnce());
    const body = JSON.parse(String(mocks.fetch.mock.calls[0][1].body));
    expect(mocks.fetch.mock.calls[0][0]).toBe("/warehouse/quality/vendor-return/confirm");
    expect(body).toMatchObject({ source_status: "QUARANTINED", vendor_name: "Supplier One", vendor_reference: "V-44", handover_reference: "H-55", quantity: "8" });
  });

  it("uses native form submission for safe Enter confirmation after required evidence", async () => {
    const data = terminalPayload("CONFIRM_DISPOSAL");
    mocks.fetch.mockResolvedValue({
      message: "ok", movement_ids: [501], product_variant_id: 118, batch_id: 41, source_location_id: 11,
      disposed_quantity: "8", remaining_quantity: "0", origin_transfer_header_ids: [71], event_type: "INVENTORY_FINAL_DISPOSAL_CONFIRMED",
    });
    const { i18n } = await mount(data);
    fireEvent.click(screen.getByRole("button", { name: i18n.t("terminalQualityActions.actions.CONFIRM_DISPOSAL.label") }));
    fireEvent.change(screen.getByLabelText(i18n.t("terminalQualityActions.disposalReason")), { target: { value: "Confirmed damage" } });
    const confirm = screen.getByRole("button", { name: i18n.t("terminalQualityActions.confirm") });
    expect(confirm).toHaveAttribute("type", "submit");
    const form = confirm.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledOnce());
  });

  it("keeps Arabic terminal UX readable, RTL, Western-digit and backend-code free", async () => {
    const data = terminalPayload("CONFIRM_DISPOSAL");
    const { i18n } = await mount(data, "ar");
    const trigger = screen.getByRole("button", { name: i18n.t("terminalQualityActions.actions.CONFIRM_DISPOSAL.label") });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(dialog.closest(".app-modal")).toHaveAttribute("dir", "rtl");
    expect(dialog).toHaveTextContent("تأكيد إتلاف الكمية فعليًا");
    expect(dialog).toHaveTextContent("8");
    expect(dialog.textContent).not.toMatch(/[٠-٩]/);
    expect(dialog.textContent).not.toMatch(/\?{2,}|CONFIRM_DISPOSAL|DISPOSAL_PENDING|RECALL_RETURN|terminal operation|durable operation/i);
    await waitFor(() => expect(screen.getByDisplayValue("8")).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("does not render a terminal command when the server says it is unavailable", async () => {
    const data = terminalPayload("CONFIRM_DISPOSAL", false);
    const { i18n } = await mount(data);
    expect(screen.queryByRole("button", { name: i18n.t("terminalQualityActions.actions.CONFIRM_DISPOSAL.label") })).not.toBeInTheDocument();
    expect(screen.getAllByText(i18n.t("terminalQualityActions.reasons.STATE_RESTRICTION"), { exact: false }).length).toBeGreaterThan(0);
  });
});
