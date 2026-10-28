import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { setAppLanguage } from "@/i18n";
import DispatchBoard from "@/pages/DispatchBoard";

const fake = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  isCompanyOwner: true, data: { company_id: 1, principal_id: 3 }, can: () => true,
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
  localStorage.clear(); localStorage.setItem("activeTab", "launch"); localStorage.setItem("wanasah_route_vehicle", "17");
  await setAppLanguage("en"); fake.fetch.mockReset();
});

it("reloads custody and the blank stock page on Warehouse/Vehicle changes, clearing drafts and ignoring late custody", async () => {
  let custodyReads = 0;
  let finishOld: (value: unknown) => void = () => {};
  fake.fetch.mockImplementation(async (url: string) => {
    if (url === "/dispatch/init") return { zones: [], drivers: [], vehicles: [
      { id: "17", label: "Vehicle one", can_execute: true }, { id: "18", label: "Vehicle two", can_execute: true },
    ], warehouses: [{ id: "21", label: "Warehouse one", can_execute: true }, { id: "22", label: "Warehouse two", can_execute: true }] };
    if (url.startsWith("/dispatch/inventory/")) {
      custodyReads += 1;
      if (custodyReads === 3) return new Promise((resolve) => { finishOld = resolve; });
      return [custody(url.endsWith("/18") ? "800" : "521", url.endsWith("/18") ? "Current vehicle two" : "Current A, zero source stock")];
    }
    if (url.startsWith("/dispatch/products?")) return url.includes("warehouse_id=21")
      ? page("900", "Eligible source B") : page("901", "New Warehouse stock");
    if (url.startsWith("/warehouse/status")) return { is_locked: false };
    return [];
  });
  render(<MemoryRouter initialEntries={["/dispatch"]}><DispatchBoard /></MemoryRouter>);
  await screen.findByRole("option", { name: "Warehouse one" });
  fireEvent.change(screen.getByRole("combobox", { name: "مستودع المصدر" }), { target: { value: "21" } });
  await screen.findByText("Eligible source B");
  await screen.findByText("Current A, zero source stock");
  await waitFor(() => expect(screen.getByRole("textbox", { name: /Target.*Eligible source B/ })).not.toBeDisabled());
  fireEvent.change(screen.getByRole("textbox", { name: /Target.*Eligible source B/ }), { target: { value: "5" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "filter" } });
  await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.includes("search=filter"))).toBe(true));

  fireEvent.change(screen.getByRole("combobox", { name: "مستودع المصدر" }), { target: { value: "22" } });
  expect(screen.getByRole("textbox", { name: "Search products" })).toHaveValue("");
  expect(screen.queryByText("Eligible source B")).not.toBeInTheDocument();
  expect(screen.queryByText("Current A, zero source stock")).not.toBeInTheDocument();
  await screen.findByText("New Warehouse stock");
  expect(screen.getByRole("textbox", { name: /Target.*New Warehouse stock/ })).toBeDisabled();
  await waitFor(() => expect(custodyReads).toBe(3));

  fireEvent.change(screen.getByRole("combobox", { name: "السيارة" }), { target: { value: "18" } });
  await screen.findByText("Current vehicle two");
  await act(async () => finishOld([custody("521", "Stale old custody")]));
  expect(screen.queryByText("Stale old custody")).not.toBeInTheDocument();
  expect(screen.queryByText("Eligible source B")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: /Target.*New Warehouse stock/ })).toHaveValue("0");
  const requests = fake.fetch.mock.calls.filter(([url]) => url.startsWith("/dispatch/products?")).map(([url]) => url);
  expect(requests.some((url) => url.includes("vehicle_id=18&warehouse_id=22&search=&limit=80"))).toBe(true);
  expect(requests.filter((url) => url.includes("warehouse_id=22")).every((url) => !url.includes("cursor="))).toBe(true);
  expect(custodyReads).toBe(4);
});
