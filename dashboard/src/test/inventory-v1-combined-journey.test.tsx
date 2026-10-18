import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { webcrypto } from "node:crypto";
import i18n from "@/i18n";
import OperationsDashboard from "@/pages/OperationsDashboard";
import { SESSION_STATUS, type SessionSettlementReport } from "@/data/operations-data";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), backofficeId: 77 }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    data: { company_id: 41, backoffice_user_id: mocks.backofficeId },
    can: () => true, canAny: () => true, isCompanyOwner: false,
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
const availableKey = "a".repeat(24);
const damagedKey = "d".repeat(24);
const report: SessionSettlementReport = {
  driver_name: "Closure representative", session_date: "2026-10-18",
  status: SESSION_STATUS.AWAITING_INVENTORY_RECONCILIATION,
  financials: { expected_cash_in_hand: "10.000", cash_from_sales: "10.000",
    cash_from_debts: "0.000", inventory_shortage_cash: "0.000" },
  visits: { completed_total: 1, successful_sales: 1, pending_remaining: 0 },
  inventory: [{
    product_id: 13, product_name: "Closure product", starting_quantity: 10,
    sold_quantity: 0, remaining_quantity: 10, packs_per_carton: 1,
    starting_cartons: 10, starting_loose_packs: 0, sold_cartons: 0,
    sold_loose_packs: 0, remaining_cartons: 10, remaining_loose_packs: 0,
  }],
  samples_given: [],
};
const lines = [
  { line_key: availableKey, stock_status: "AVAILABLE", expected_quantity: "6" },
  { line_key: damagedKey, stock_status: "DAMAGED", expected_quantity: "4" },
].map(row => ({ ...row, product_name: "Closure product", sku: "CLOSE-SKU",
  batch_number: "CLOSE-LOT", expiry_date: null, uom: "EACH" }));

type Wire = Record<string, unknown>;
type CountRow = { line_key: string; actual_quantity: string };
function fixtureServer({ variance = false, dropFinancialResponse = false } = {}) {
  let received = false;
  let review = false;
  let recount = false;
  let independent = false;
  let approved = false;
  let closed = false;
  let financialEffects = 0;
  let dropped = false;
  const commands = new Map<string, { body: string; response: Wire }>();
  const writes: Array<{ url: string; body: Wire; actor: number }> = [];
  const status = () => closed ? SESSION_STATUS.SETTLED
    : received ? SESSION_STATUS.AWAITING_FINANCIAL_SETTLEMENT
      : SESSION_STATUS.AWAITING_INVENTORY_RECONCILIATION;
  const fault = (code: string, statusCode = 409) => Object.assign(new Error(code), {
    status: statusCode, code, context: {}, requestId: "closure-fixture-request",
  });
  mocks.fetch.mockImplementation(async (url: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    if (method === "GET") {
      if (url.startsWith("/admin/sessions/today")) return [{
        session: { session_id: 19, driver_name: report.driver_name, start_time: null,
          is_authorized_to_sell: false, is_on_break: false, vehicle_label: "Closure vehicle" },
        settlement: { ...report, status: status() },
      }];
      if (url.endsWith("/settlement_report")) return { ...report, status: status() };
      if (url.endsWith("/inventory-custody")) return {
        work_session_id: 19, vehicle_location_id: 8, inventory_reconciled: approved || received,
        custody_received: received, review_required: review && !approved,
        reconciliation_reference: review ? "VREC-CLOSURE" : null,
        lines: received ? [] : lines.map(row => ({ ...row,
          expected_quantity: approved && row.stock_status === "DAMAGED" ? "3" : row.expected_quantity })),
      };
      if (url.endsWith("/variance")) return {
        status: "REVIEW_REQUIRED", reconciliation_reference: "VREC-CLOSURE",
        independent_recount_satisfied: independent, requires_independent_recount: true,
        attempt_number: independent ? 2 : 1,
        lines: lines.map(row => ({ ...row, actual_quantity: row.stock_status === "DAMAGED" ? "3" : "6",
          variance_quantity: row.stock_status === "DAMAGED" ? "-1" : "0" })),
      };
      if (url.endsWith("/variance/count-sheet")) {
        if (!recount || mocks.backofficeId !== 88) throw fault("INDEPENDENT_COUNTER_REQUIRED", 403);
        return { status: "RECOUNT_REQUIRED", reconciliation_reference: "VREC-CLOSURE",
          lines: lines.map(row => ({
            line_key: row.line_key, stock_status: row.stock_status,
            product_name: row.product_name, batch_number: row.batch_number,
            expiry_date: row.expiry_date, uom: row.uom,
          })) };
      }
      if (url.includes("/locations/manage") || url.includes("/transfer/locations")) {
        const warehouse = { id: 7, name: "Only Warehouse", code: "ONLY-WH",
          location_type: "WAREHOUSE", vehicle_id: null, is_active: true };
        return url.includes("/transfer/locations") ? [warehouse]
          : { items: [warehouse], total: 1, next_cursor: null, has_more: false };
      }
      throw fault("UNEXPECTED_READ_" + url, 500);
    }
    const body = JSON.parse(String(options?.body)) as Wire;
    writes.push({ url, body, actor: mocks.backofficeId });
    expect(body).not.toHaveProperty("inventory_jard");
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/i);
    const identity = String(body.request_id);
    const saved = commands.get(identity);
    if (saved) {
      if (saved.body !== JSON.stringify(body)) throw fault("IDEMPOTENCY_CONFLICT");
      return saved.response;
    }
    let response: Wire;
    if (url.endsWith("/inventory-custody/receive")) {
      expect(body.receiver_confirms_handoff).toBe(true);
      expect(body.destination_location_id).toBe(7);
      const items = body.items as CountRow[];
      expect(new Set(items.map(row => row.line_key))).toEqual(new Set([availableKey, damagedKey]));
      if (variance && !approved) {
        expect(Number(items.find(row => row.line_key === damagedKey)?.actual_quantity)).toBe(3);
        review = true;
        response = { status: "REVIEW_REQUIRED", review_required: true,
          requires_independent_recount: true, reconciliation_reference: "VREC-CLOSURE",
          movement_count: 0 };
      } else {
        expect(variance ? independent && approved : true).toBe(true);
        received = true;
        response = { status: "CUSTODY_RECEIVED", review_required: false,
          inventory_reconciled: true, movement_count: 2, financial_ready: true };
      }
    } else if (url.endsWith("/variance/recount")) {
      expect(review).toBe(true);
      expect(body.authorizer_username).toBe("Independent receiver");
      expect(body.authorizer_password).toBe("IndependentPassword123");
      recount = true;
      response = { status: "RECOUNT_REQUIRED", reconciliation_reference: "VREC-CLOSURE",
        recount_authorized: true };
    } else if (url.endsWith("/variance/count")) {
      expect(mocks.backofficeId).toBe(88);
      expect(recount).toBe(true);
      independent = true;
      response = { status: "REVIEW_REQUIRED", reconciliation_reference: "VREC-CLOSURE",
        attempt_number: 2, requires_independent_recount: true };
    } else if (url.endsWith("/variance/approve")) {
      expect(independent).toBe(true);
      expect(mocks.backofficeId).toBe(77);
      approved = true;
      response = { status: "RECONCILED_AWAITING_RECEIPT", receiver_must_confirm_handoff: true,
        financial_ready: false, movement_count: 1, reconciliation_reference: "VREC-CLOSURE" };
    } else if (url.endsWith("/settle")) {
      expect(received).toBe(true);
      if (closed) throw fault("ALREADY_CLOSED");
      expect(Number(body.actual_cash)).toBe(10);
      closed = true;
      financialEffects += 1;
      response = { is_settled: true, cash_difference: "0.000", message: "Closed" };
      commands.set(identity, { body: JSON.stringify(body), response });
      if (dropFinancialResponse && !dropped) {
        dropped = true;
        throw fault("NETWORK_UNAVAILABLE", 0); // server committed; response deliberately lost
      }
    } else throw fault("UNEXPECTED_MUTATION_" + url, 500);
    commands.set(identity, { body: JSON.stringify(body), response });
    return response;
  });
  return { writes, effects: () => financialEffects, received: () => received, closed: () => closed };
}
const mount = () => render(<MemoryRouter><OperationsDashboard /></MemoryRouter>);
async function openYellowEntry() {
  const representative = await screen.findByText("Closure representative");
  fireEvent.click(representative);
  const entry = await screen.findByRole("button", {
    name: /اعتماد التسوية وإغلاق العهدة|بدء.*التسوية|تسوية.*مندوب|Start.*settlement|Settle.*custody|Representative settlement/i,
  });
  expect(entry).toBeEnabled(); // an ended UNSEALED session must be eligible
  fireEvent.click(entry);
  await waitFor(() => expect(mocks.fetch.mock.calls.some(([url]) =>
    String(url).endsWith("/inventory-custody"))).toBe(true));
  return screen.findByRole("dialog");
}
function count(dialog: HTMLElement, status: "AVAILABLE" | "DAMAGED", value: string) {
  // Business labels; no database IDs or CSS classes are required from the operator.
  const label = status === "AVAILABLE" ? /AVAILABLE|Available|متاح/i : /DAMAGED|Damaged|تالف/i;
  fireEvent.change(within(dialog).getByLabelText(label), { target: { value } });
}
async function confirmReceipt(dialog: HTMLElement, damaged = "4") {
  count(dialog, "AVAILABLE", "6");
  count(dialog, "DAMAGED", damaged);
  const destination = within(dialog).queryByRole("combobox", { name: /Warehouse|مستودع/i });
  if (destination) fireEvent.change(destination, { target: { value: "7" } });
  const confirmation = within(dialog).queryByRole("checkbox", { name: /confirm|received|أؤكد|استلم/i });
  if (confirmation) fireEvent.click(confirmation);
  fireEvent.click(within(dialog).getByRole("button", {
    name: /Confirm.*(receipt|handoff)|Receive.*goods|تأكيد.*استلام|اعتماد.*استلام/i,
  }));
}
async function closeFinancial(server: ReturnType<typeof fixtureServer>, lostResponse = false) {
  const dialog = await screen.findByRole("dialog");
  await waitFor(() => expect(server.received()).toBe(true));
  const cash = await within(dialog).findByLabelText(/actual.*cash|cash.*received|الكاش.*الفعلي|النقد.*الفعلي/i);
  fireEvent.change(cash, { target: { value: "10.000" } });
  expect(within(dialog).queryByLabelText(/DAMAGED|AVAILABLE|تالف|متاح/i)).toBeNull();
  const confirm = /Confirm.*(financial|settlement)|Close.*settlement|اعتماد.*التسوية|إغلاق.*العهدة/i;
  fireEvent.click(within(dialog).getByRole("button", { name: confirm }));
  await waitFor(() => expect(server.effects()).toBe(1));
  if (lostResponse) {
    const retry = await within(dialog).findByRole("button", {
      name: /Retry|إعادة المحاولة|إعادة الإرسال|اعتماد.*التسوية|Confirm.*settlement/i,
    });
    fireEvent.click(retry);
    await waitFor(() => expect(server.writes.filter(r => r.url.endsWith("/settle"))).toHaveLength(2));
    const attempts = server.writes.filter(r => r.url.endsWith("/settle"));
    expect(attempts[1].body).toEqual(attempts[0].body);
  }
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(server.effects()).toBe(1);
  expect(server.writes.every(row => !("inventory_jard" in row.body))).toBe(true);
}
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("company_id", "41");
  localStorage.setItem("principal_id", "91");
  localStorage.setItem("backoffice_user_id", "77");
  mocks.backofficeId = 77;
  mocks.fetch.mockReset();
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
});
afterEach(cleanup);

describe("Combined candidate positive yellow-card settlement", () => {
  it.each(["en", "ar"])("previews AVAILABLE + DAMAGED, receives, then financially closes (%s)", async language => {
    await i18n.changeLanguage(language);
    const server = fixtureServer();
    mount();
    const dialog = await openYellowEntry();
    expect(within(dialog).getAllByText("CLOSE-LOT").length).toBeGreaterThan(0);
    await confirmReceipt(dialog);
    await closeFinancial(server);
    expect(server.writes.filter(row => row.url.endsWith("/receive"))).toHaveLength(1);
    expect(server.writes.filter(row => row.url.endsWith("/settle"))).toHaveLength(1);
  });

  it.each(["en", "ar"])("keeps variance explicit through independent recount, approval and receiving (%s)", async language => {
    await i18n.changeLanguage(language);
    const server = fixtureServer({ variance: true });
    let rendered = mount();
    let dialog = await openYellowEntry();
    await confirmReceipt(dialog, "3");
    expect((await within(dialog).findAllByText(/[-−]\\s*[1١]/)).length).toBeGreaterThan(0);
    expect(server.writes.some(row => row.url.endsWith("/settle"))).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: /Recount|إعادة.*عد/i }));
    fireEvent.change(within(dialog).getByLabelText(/username|authorizer|اسم المستخدم/i),
      { target: { value: "Independent receiver" } });
    fireEvent.change(within(dialog).getByLabelText(/password|كلمة المرور/i),
      { target: { value: "IndependentPassword123" } });
    const reason = within(dialog).queryByLabelText(/reason|سبب/i);
    if (reason) fireEvent.change(reason, { target: { value: "Independent physical recount" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Authorize.*recount|Request.*recount|تفويض.*عد|اعتماد.*عد/i }));
    await waitFor(() => expect(server.writes.some(row => row.url.endsWith("/variance/recount"))).toBe(true));
    rendered.unmount();
    mocks.backofficeId = 88;
    localStorage.setItem("backoffice_user_id", "88");
    rendered = mount();
    dialog = await openYellowEntry();
    count(dialog, "AVAILABLE", "6");
    count(dialog, "DAMAGED", "3");
    fireEvent.click(within(dialog).getByRole("button", { name: /Submit.*count|Finish.*count|تثبيت.*عد|إنهاء.*عد/i }));
    await waitFor(() => expect(server.writes.some(row => row.url.endsWith("/variance/count"))).toBe(true));
    rendered.unmount();
    mocks.backofficeId = 77;
    localStorage.setItem("backoffice_user_id", "77");
    mount();
    dialog = await openYellowEntry();
    expect((await within(dialog).findAllByText(/[-−]\\s*[1١]/)).length).toBeGreaterThan(0);
    const password = within(dialog).queryByLabelText(/password|كلمة المرور/i);
    if (password) fireEvent.change(password, { target: { value: "ReceiverPassword123" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Approve.*variance|Final approval|اعتماد.*فرق|اعتماد نهائي/i }));
    await waitFor(() => expect(server.writes.some(row => row.url.endsWith("/variance/approve"))).toBe(true));
    expect(server.received()).toBe(false); // approval is never an automatic handoff
    await confirmReceipt(dialog, "3");
    await closeFinancial(server);
  });

  it("recovers a committed financial response loss using the identical command", async () => {
    await i18n.changeLanguage("en");
    const server = fixtureServer({ dropFinancialResponse: true });
    mount();
    await confirmReceipt(await openYellowEntry());
    await closeFinancial(server, true);
  });
});
