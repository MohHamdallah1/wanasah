import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { setAppLanguage } from "@/i18n";
import DispatchBoard from "@/pages/DispatchBoard";
import { writeDispatchPreferences } from "@/features/dispatch/sessionScope";

const fake = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
// D13 Shop children use verified tenant money. This legacy Warehouse fixture has
// no QueryClient, so provide the exact one-company currency without changing reads.
vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: { company_id: 1, currency_code: "QAR" } }),
}));
const ownerGrants = {
  company_id: 1, principal_id: 3, backoffice_user_id: 13,
  is_company_owner: true, location_id: null,
  permissions: ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"],
  any_permissions: ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"],
  location_permissions: [],
};
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  isCompanyOwner: true, data: ownerGrants, can: () => true,
  isFetching: false, isError: false, error: null, dataUpdatedAt: 100,
  refetch: async () => ({ data: ownerGrants }),
}) }));
vi.mock("@/components/ui/custom-select", () => ({ CustomSelect: ({ label, value, options, onChange }: {
  label: string; value: string; options: { id: string; label: string }[]; onChange: (value: string) => void;
}) => <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
  <option value="" />{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
</select> }));
const unit = { base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "EACH", quantity_scale: 0,
  quantity_step: "1", display_uom_name: "PACK", display_factor_to_base: "8" };
const custody = (id: string, name: string) => ({ ...unit, product_id: id, product_name: name,
  current_base_quantity: "25", current_quantity: 3 });
const page = (id: string, name: string) => ({ items: [{ id, name, load: { ...unit, product_id: id, product_name: name,
  current_base_quantity: "0", reserved_base_quantity: "0", pending_base_quantity: "0" } }], next_cursor: null, has_more: false });

beforeEach(async () => {
  vi.stubGlobal("WebSocket", class {
    static OPEN = 1; static CONNECTING = 0; static CLOSED = 3;
    readyState = 0;
    send() {}
    close() { this.readyState = 3; }
  });
  localStorage.clear();
  localStorage.setItem("admin_token", "synthetic-load-context-only");
  localStorage.setItem("company_id", "1"); localStorage.setItem("principal_id", "3");
  localStorage.setItem("backoffice_user_id", "13");
  writeDispatchPreferences("1:3:13", {
    activeTab: "launch", zoneForShops: "", launchZone: "", driver: "",
    vehicle: "17", sourceWarehouse: "21",
  });
  await setAppLanguage("en"); fake.fetch.mockReset();
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// Exercise the actual signed M05 listbox, not the obsolete native select mock.
const pick = async (kind: "warehouses" | "vehicles", label: string) => {
  const box = await screen.findByTestId("m05-launch-" + kind);
  await waitFor(() => expect(within(box).getByRole("button")).not.toBeDisabled());
  fireEvent.click(within(box).getByRole("button"));
  fireEvent.click(within(box).getByRole("option", { name: label }));
};

it("reloads custody and the blank stock page on Warehouse/Vehicle changes, clearing drafts and ignoring late custody", async () => {
  let custodyReads = 0;
  let finishOld: (value: unknown) => void = () => {};
  fake.fetch.mockImplementation(async (url: string) => {
    if (url.startsWith("/dispatch/launch/resource-availability")) return {
      advisory: true, zones: [], drivers: [],
      vehicles: ["17", "18"].map((id, i) => ({
        id, label: i ? "Vehicle two" : "Vehicle one", available: true, code: "AVAILABLE",
      })),
      warehouses: ["21", "22"].map((id, i) => ({
        id, label: i ? "Warehouse two" : "Warehouse one", available: true, code: "AVAILABLE",
      })),
    };
    if (url === "/dispatch/init") return { zones: [], drivers: [], vehicles: [
      { id: "17", label: "Vehicle one", can_execute: true }, { id: "18", label: "Vehicle two", can_execute: true },
    ], warehouses: [{ id: "21", label: "Warehouse one", can_execute: true }, { id: "22", label: "Warehouse two", can_execute: true }] };
    if (url.startsWith("/dispatch/inventory/")) {
      custodyReads += 1;
      if (custodyReads === 2) return new Promise((resolve) => { finishOld = resolve; });
      return [custody(url.endsWith("/18") ? "800" : "521", url.endsWith("/18") ? "Current vehicle two" : "Current A, zero source stock")];
    }
    if (url.startsWith("/dispatch/products?")) return url.includes("warehouse_id=21")
      ? page("900", "Eligible source B") : page("901", "New Warehouse stock");
    if (url.startsWith("/warehouse/status")) return { is_locked: false };
    return [];
  });
  render(<MemoryRouter initialEntries={["/dispatch"]}><DispatchBoard /></MemoryRouter>);
  await pick("warehouses", "Warehouse one");
  await screen.findByText("Eligible source B");
  await screen.findByText("Current A, zero source stock");
  await waitFor(() => expect(screen.getByRole("textbox", { name: /Target.*Eligible source B.*EACH/ })).not.toBeDisabled());
  fireEvent.change(screen.getByRole("textbox", { name: /Target.*Eligible source B.*EACH/ }), { target: { value: "5" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "filter" } });
  await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.includes("search=filter"))).toBe(true));

  // A second in-flight A custody read is deliberately delayed; changing
  // source Warehouse must clear the old Vehicle selection and reject that result.
  await pick("vehicles", "Vehicle two");
  await waitFor(() => expect(custodyReads).toBe(2));
  await pick("warehouses", "Warehouse two");
  expect(within(screen.getByTestId("m05-launch-vehicles")).getByRole("button"))
    .toHaveTextContent("Select vehicle");
  expect(screen.getByRole("textbox", { name: "Search products" })).toHaveValue("");
  expect(screen.queryByText("Eligible source B")).not.toBeInTheDocument();
  expect(screen.queryByText("Current A, zero source stock")).not.toBeInTheDocument();
  // The product selector deliberately stays disabled without a Vehicle after
  // the Warehouse handoff. Re-selecting a Vehicle starts a fresh authorized read.
  expect(screen.queryByText("New Warehouse stock")).not.toBeInTheDocument();
  await waitFor(() => expect(custodyReads).toBe(2));

  await pick("vehicles", "Vehicle two");
  await screen.findByText("New Warehouse stock");
  await screen.findByText("Current vehicle two");
  // A newly selected, authorized Vehicle is editable with an empty zero-equivalent draft.
  expect(screen.getByRole("textbox", { name: /Target.*New Warehouse stock.*EACH/ })).not.toBeDisabled();
  await act(async () => finishOld([custody("521", "Stale old custody")]));
  expect(screen.queryByText("Stale old custody")).not.toBeInTheDocument();
  expect(screen.queryByText("Eligible source B")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: /Target.*New Warehouse stock.*EACH/ })).toHaveValue("");
  const requests = fake.fetch.mock.calls.filter(([url]) => url.startsWith("/dispatch/products?")).map(([url]) => url);
  expect(requests.some((url) => url.includes("vehicle_id=18&warehouse_id=22&search=&limit=80"))).toBe(true);
  expect(requests.filter((url) => url.includes("warehouse_id=22")).every((url) => !url.includes("cursor="))).toBe(true);
  expect(custodyReads).toBe(3);
});
