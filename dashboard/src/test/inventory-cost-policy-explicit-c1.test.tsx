import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  parseCostPolicy,
} from "@/pages/inventory/inbound/contracts";

const mock = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: mock.toastError, success: mock.toastSuccess },
}));

vi.mock("@/features/suppliers/SupplierSelector", () => ({
  SupplierSelector: () => <div data-testid="supplier-selector" />,
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  const t = (key: string) => key;
  const i18n = { language: "en", resolvedLanguage: "en", dir: () => "ltr" };
  return { ...actual, useTranslation: () => ({ t, i18n }) };
});

import { Tab2Inbound } from "@/pages/inventory/Tab2Inbound";

const unselected = {
  method: null,
  is_selected: false,
  selection_status: "UNSELECTED",
  selected_at: null,
  is_active: false,
  is_locked: false,
  locked_at: null,
  version: 1,
  currency_code: "JOD",
  can_change: true,
} as const;

const selected = {
  ...unselected,
  method: "MOVING_AVERAGE",
  is_selected: true,
  selection_status: "SELECTED",
  selected_at: "2026-09-29T07:00:00",
  version: 2,
} as const;

function makeFetch(initial: Record<string, unknown>) {
  return vi.fn(async (url: string, opts?: RequestInit): Promise<unknown> => {
    if (url.startsWith("/catalog/variants?")) {
      return { items: [], next_cursor: null, has_more: false };
    }
    if (url === "/warehouse/costing-policy" && !opts) return initial;
    if (url === "/warehouse/costing-policy" && opts?.method === "PUT") {
      return { ...selected, method: JSON.parse(String(opts.body)).method };
    }
    throw new Error("Unexpected request: " + url);
  });
}

function page(fetch: ReturnType<typeof makeFetch>) {
  return render(
    <Tab2Inbound
      companyId={38}
      actorId={26}
      locationId={13}
      isAuditLocked={false}
      authenticatedFetch={fetch}
      onSuccess={vi.fn()}
    />,
  );
}

describe("cost method selection C1 / no phantom moving-average", () => {
  beforeEach(() => {
    localStorage.clear();
    mock.toastError.mockReset();
    mock.toastSuccess.mockReset();
  });

  it("parses selected, missing and historical active cost policy distinctly", () => {
    expect(parseCostPolicy(unselected)).toMatchObject({
      method: null,
      is_selected: false,
      selection_status: "UNSELECTED",
    });
    expect(parseCostPolicy(selected).is_selected).toBe(true);
    expect(
      parseCostPolicy({
        ...selected,
        method: "FIFO",
        is_active: true,
        is_locked: true,
        locked_at: "2026-09-29T07:01:00",
        can_change: false,
        selected_at: null,
        selection_status: "LEGACY_ACTIVE",
      }).method,
    ).toBe("FIFO");
  });

  it.each([
    { ...unselected, method: "MOVING_AVERAGE" },
    { ...unselected, is_selected: true },
    { ...selected, selected_at: null },
    { ...selected, selection_status: "UNSELECTED" },
    { ...selected, method: "FAKE" },
    { ...selected, is_selected: "true" },
    { ...unselected, selected_at: "2026-09-29T07:00:00" },
    { ...selected, is_active: true, is_locked: false },
    { ...selected, is_active: true, is_locked: true, locked_at: null },
    { ...selected, is_active: true, is_locked: true, locked_at: "2026-09-29T07:00:00", can_change: true },
  ])("fails closed on inconsistent selection DTO (%#)", (invalid) => {
    expect(() => parseCostPolicy(invalid)).toThrow();
  });

  it("keeps an unselected costing policy out of the daily inbound screen", async () => {
    const fetch = makeFetch(unselected);
    page(fetch);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) => url === "/warehouse/costing-policy"),
      ).toBe(true),
    );
    expect(
      screen.queryByRole("combobox", {
        name: "inventoryInbound.costMethod",
      }),
    ).toBeNull();
    expect(
      screen.queryByText("inventoryInbound.costMethodRequired"),
    ).toBeNull();
    expect(
      fetch.mock.calls.some(
        ([url, opts]) =>
          url === "/warehouse/costing-policy" && opts?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("never auto-saves a costing method merely by opening inbound", async () => {
    const fetch = makeFetch(unselected);
    page(fetch);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) => url === "/warehouse/costing-policy"),
      ).toBe(true),
    );
    expect(
      fetch.mock.calls.filter(
        ([url, opts]) =>
          url === "/warehouse/costing-policy" && opts?.method === "PUT",
      ),
    ).toHaveLength(0);
  });

  it("keeps an unauthorized unselected policy hidden until first valid posting", async () => {
    const fetch = makeFetch({ ...unselected, can_change: false });
    page(fetch);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) => url === "/warehouse/costing-policy"),
      ).toBe(true),
    );
    expect(
      screen.queryByText("inventoryInbound.costMethodNoPermission"),
    ).toBeNull();
    expect(
      screen.queryByRole("combobox", {
        name: "inventoryInbound.costMethod",
      }),
    ).toBeNull();
  });

  it("preserves historical active FIFO without exposing a daily policy control", async () => {
    const fetch = makeFetch({
      ...selected,
      method: "FIFO",
      selected_at: null,
      selection_status: "LEGACY_ACTIVE",
      is_active: true,
      is_locked: true,
      locked_at: "2026-09-29T07:01:00",
      can_change: false,
    });
    page(fetch);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) => url === "/warehouse/costing-policy"),
      ).toBe(true),
    );
    expect(
      screen.queryByRole("combobox", {
        name: "inventoryInbound.costMethod",
      }),
    ).toBeNull();
    expect(
      fetch.mock.calls.some(
        ([url, opts]) =>
          url === "/warehouse/costing-policy" && opts?.method === "PUT",
      ),
    ).toBe(false);
  });
});