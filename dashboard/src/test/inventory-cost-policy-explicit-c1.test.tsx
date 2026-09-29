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
  ])("fails closed on inconsistent selection DTO (%#)", (invalid) => {
    expect(() => parseCostPolicy(invalid)).toThrow();
  });

  it("shows no default choice and disables first receipt until explicitly saved", async () => {
    const fetch = makeFetch(unselected);
    page(fetch);
    const select = screen.getByRole("combobox", {
      name: "inventoryInbound.costMethod",
    }) as HTMLSelectElement;
    await waitFor(() => {
      expect(screen.getByText("inventoryInbound.costMethodRequired")).toBeTruthy();
    });
    expect(select.value).toBe("");
    expect(
      (screen.getByRole("button", {
        name: "inventoryInbound.submit",
      }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(fetch.mock.calls.some(([url, opts]) =>
      url === "/warehouse/costing-policy" && opts?.method === "PUT",
    )).toBe(false);
  });

  it("saving the displayed default is an explicit authorized PUT before posting", async () => {
    const fetch = makeFetch(unselected);
    page(fetch);
    const select = screen.getByRole("combobox", {
      name: "inventoryInbound.costMethod",
    }) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    fireEvent.change(select, { target: { value: "MOVING_AVERAGE" } });
    await waitFor(() => {
      expect(select.value).toBe("MOVING_AVERAGE");
      expect(
        (screen.getByRole("button", {
          name: "inventoryInbound.submit",
        }) as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    const writes = fetch.mock.calls.filter(([url, opts]) =>
      url === "/warehouse/costing-policy" && opts?.method === "PUT",
    );
    expect(writes).toHaveLength(1);
    const body = JSON.parse(String(writes[0][1]?.body));
    expect(body).toMatchObject({
      method: "MOVING_AVERAGE",
      expected_version: 1,
    });
    expect(typeof body.request_id).toBe("string");
  });

  it("keeps unselected receipts disabled when the user cannot manage costing", async () => {
    const fetch = makeFetch({ ...unselected, can_change: false });
    page(fetch);
    await waitFor(() => {
      expect(screen.getByText("inventoryInbound.costMethodNoPermission")).toBeTruthy();
    });
    const select = screen.getByRole("combobox", {
      name: "inventoryInbound.costMethod",
    }) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(select.value).toBe("");
  });

  it("preserves previously active legacy FIFO and disables policy changes", async () => {
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
    const select = screen.getByRole("combobox", {
      name: "inventoryInbound.costMethod",
    }) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("FIFO"));
    expect(select.disabled).toBe(true);
    expect(
      (screen.getByRole("button", {
        name: "inventoryInbound.submit",
      }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});
