import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import i18n from "@/i18n";
import { TabWarehouseLocations } from "@/pages/inventory/TabWarehouseLocations";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), policyAllowed: true }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    isCompanyOwner: true,
    data: { company_id: 41, backoffice_user_id: 77 },
    can: (code: string) => code === "inventory.transfer_policy.manage"
      ? mocks.policyAllowed : code === "location.read",
    canAny: (code: string) => code === "location.read",
  }),
  useLocationCapabilities: () => () => false,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const warehouse = {
  id: 7, name: "Only Warehouse", code: "ONLY-WH", address: "Acceptance address",
  location_link: null, latitude: null, longitude: null, branch_id: null,
  branch_name: null, is_active: true, version: 1,
  created_at: "2026-10-18T00:00:00Z", updated_at: "2026-10-18T00:00:00Z",
};
const explicit = {
  draft: null, published: {
    id: 11, revision: 4, status: "PUBLISHED",
    validated_payload: {
      quarantine_location_id: 21, disposal_location_id: 22,
      vendor_return_staging_location_id: 23, allow_retiring_warehouse_balancing: false,
    },
  },
};
const sameLocation = () => i18n.t("transferDestinationSetup.sameLocation");
const policyCalls = () => mocks.fetch.mock.calls.filter(([url]) =>
  String(url).includes("/operational-policy/transfer-destinations"));
const view = () => render(<TabWarehouseLocations
  selectedLocationId={7} onLocationsChanged={vi.fn()} onMinimumApplied={vi.fn()}
/>);
async function openUtility() {
  await screen.findAllByText("Only Warehouse");
  const button = screen.getByRole("button", { name: /Quality destinations|وجهات الجودة/i });
  expect(button).toBeEnabled();
  fireEvent.click(button);
  return screen.findByRole("dialog", { name: /Quality destinations|وجهات الجودة/i });
}
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("company_id", "41");
  localStorage.setItem("principal_id", "91");
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  mocks.policyAllowed = true;
  mocks.fetch.mockReset();
});
afterEach(cleanup);
function transport(policy: () => unknown | Promise<unknown>) {
  mocks.fetch.mockImplementation(async (url: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") throw new Error("Opening must not mutate");
    if (url.includes("/operational-policy/transfer-destinations")) return policy();
    if (url.includes("/locations/manage")) return {
      items: [warehouse], total: 1, next_cursor: null, has_more: false,
    };
    throw new Error("Unexpected read: " + url);
  });
}

describe("Combined candidate Quality destinations truth", () => {
  it.each(["en", "ar"])("one-Warehouse utility opens with no setup writes (%s)", async language => {
    await i18n.changeLanguage(language);
    transport(() => ({ draft: null, published: null }));
    view();
    await screen.findAllByText("Only Warehouse");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(policyCalls()).toHaveLength(0);
    const dialog = await openUtility();
    await waitFor(() => expect(within(dialog).getAllByText(sameLocation())).toHaveLength(3));
    expect(dialog.closest("[dir]")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    expect(within(dialog).queryByRole("combobox")).toBeNull();
    expect(mocks.fetch.mock.calls.every(([, options]) =>
      !options?.method || options.method === "GET")).toBe(true);
    expect(policyCalls()).toHaveLength(1);
  });

  it.each(["en", "ar"])("explicit legacy policy is NEVER called same-location, including loading (%s)", async language => {
    await i18n.changeLanguage(language);
    let resolvePolicy!: (value: unknown) => void;
    transport(() => new Promise(resolve => { resolvePolicy = resolve; }));
    view();
    const dialog = await openUtility();
    await waitFor(() => expect(policyCalls()).toHaveLength(1));
    // Unknown/pending is not proof of the default. Do not flash a false default.
    expect(within(dialog).queryByText(sameLocation())).toBeNull();
    await act(async () => resolvePolicy(explicit));
    await waitFor(() => expect(within(dialog).getByText(
      i18n.t("transferDestinationSetup.reference", { id: 21 }),
    )).toBeInTheDocument());
    for (const id of [21, 22, 23]) expect(within(dialog).getByText(
      i18n.t("transferDestinationSetup.reference", { id }),
    )).toBeInTheDocument();
    expect(within(dialog).queryByText(sameLocation())).toBeNull();
    expect(policyCalls()).toHaveLength(1);
    expect(mocks.fetch.mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
  });

  it("drops previous-company routing immediately while the next company loads", async () => {
    await i18n.changeLanguage("en");
    transport(() => explicit);
    const rendered = view();
    const dialog = await openUtility();
    await within(dialog).findByText(i18n.t("transferDestinationSetup.reference", { id: 21 }));
    localStorage.setItem("company_id", "42");
    transport(() => new Promise(() => {}));
    rendered.rerender(<TabWarehouseLocations
      selectedLocationId={7} onLocationsChanged={vi.fn()} onMinimumApplied={vi.fn()}
    />);
    expect(screen.queryByText(i18n.t("transferDestinationSetup.reference", { id: 21 }))).toBeNull();
    expect(screen.queryByText(sameLocation())).toBeNull(); // no invented next-tenant default
  });

  it("does not infer utility access from the Owner flag", async () => {
    await i18n.changeLanguage("en");
    mocks.policyAllowed = false;
    transport(() => explicit);
    view();
    await screen.findAllByText("Only Warehouse");
    expect(screen.queryByRole("button", { name: /Quality destinations|وجهات الجودة/i })).toBeNull();
    expect(policyCalls()).toHaveLength(0);
  });

  it("renders each mixed legacy destination truthfully without overwriting it", async () => {
    await i18n.changeLanguage("en");
    transport(() => ({ draft: null, published: {
      ...explicit.published, validated_payload: {
        ...explicit.published.validated_payload, quarantine_location_id: null,
        vendor_return_staging_location_id: null,
      },
    } }));
    view();
    const dialog = await openUtility();
    await within(dialog).findByText(i18n.t("transferDestinationSetup.reference", { id: 22 }));
    expect(within(dialog).getAllByText(sameLocation())).toHaveLength(2);
    expect(policyCalls()).toHaveLength(1);
    expect(mocks.fetch.mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
  });
});
