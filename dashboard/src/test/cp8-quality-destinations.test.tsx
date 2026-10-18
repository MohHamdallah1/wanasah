import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import i18n from "@/i18n";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), allowed: true }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    can: (code: string) =>
      mocks.allowed && code === "inventory.transfer_policy.manage",
    isCompanyOwner: true,
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { QualityHandlingDestinationsCard } from "@/features/inventory/quality/QualityHandlingDestinationsCard";

const payload = {
  quarantine_location_id: null,
  disposal_location_id: null,
  vendor_return_staging_location_id: null,
  allow_retiring_warehouse_balancing: false,
};
const draft = {
  id: 3,
  revision: 1,
  status: "DRAFT" as const,
  validated_payload: payload,
};

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "91");
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: webcrypto,
  });
  mocks.allowed = true;
  mocks.fetch.mockReset();
  await i18n.changeLanguage("en");
});
afterEach(cleanup);

it("does not infer policy permission from an Owner UI flag", () => {
  mocks.allowed = false;
  render(<QualityHandlingDestinationsCard />);
  expect(screen.queryByRole("button")).toBeNull();
  expect(mocks.fetch).not.toHaveBeenCalled();
});

it("uses same-location defaults without loading or requiring warehouse options", async () => {
  mocks.fetch.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (!options?.method) return { draft: null, published: null };
    if (options.method === "PUT") return { policy: draft };
    return { policy: { ...draft, status: "PUBLISHED" } };
  });

  render(<QualityHandlingDestinationsCard />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
  );

  expect(screen.queryByRole("combobox")).toBeNull();
  expect(
    mocks.fetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/locations/manage"),
    ),
  ).toBe(false);
  expect(screen.getAllByText("Same current location")).toHaveLength(3);

  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
  );
  const write = mocks.fetch.mock.calls.find(
    ([, options]) => options?.method === "PUT",
  )!;
  const body = JSON.parse(write[1].body as string);
  expect(body.payload).toEqual(payload);
});

it("recovers save and apply lost responses with original IDs after remount", async () => {
  let draftAttempts = 0;
  let publishAttempts = 0;
  let state: {
    draft: typeof draft | null;
    published: typeof draft | null;
  } = { draft: null, published: null };

  mocks.fetch.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (!options?.method) return state;
    if (options.method === "PUT") {
      state = { draft, published: null };
      if (++draftAttempts === 1) {
        throw Object.assign(new Error(), {
          status: 0,
          code: "NETWORK_UNAVAILABLE",
        });
      }
      return { policy: draft };
    }
    const published = { ...draft, status: "PUBLISHED" as const };
    state = { draft: null, published };
    if (++publishAttempts === 1) {
      throw Object.assign(new Error(), { status: 503 });
    }
    return { policy: published };
  });

  const first = render(<QualityHandlingDestinationsCard />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText(/result is unconfirmed/);

  const firstId = JSON.parse(
    mocks.fetch.mock.calls.find(([, options]) => options?.method === "PUT")![1]
      .body as string,
  ).request_id;
  first.unmount();

  render(<QualityHandlingDestinationsCard />);
  await screen.findByText(/result is unconfirmed/);
  expect(draftAttempts).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(draftAttempts).toBe(2));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
  );

  const writes = mocks.fetch.mock.calls.filter(
    ([, options]) => options?.method === "PUT",
  );
  expect(JSON.parse(writes[1][1].body as string).request_id).toBe(firstId);

  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await screen.findByText(/result is unconfirmed/);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(publishAttempts).toBe(2));

  const publishes = mocks.fetch.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(JSON.parse(publishes[1][1].body as string).request_id).toBe(
    JSON.parse(publishes[0][1].body as string).request_id,
  );
});

it.each(["ar", "en"])(
  "uses locale direction and translated in-place setup labels (%s)",
  async (language) => {
    await i18n.changeLanguage(language);
    mocks.fetch.mockResolvedValue({ draft: null, published: null });
    render(<QualityHandlingDestinationsCard />);
    const heading = await screen.findByRole("heading", { level: 3 });
    expect(heading.closest("section")).toHaveAttribute(
      "dir",
      language === "ar" ? "rtl" : "ltr",
    );
    expect(heading.textContent).toBe(
      language === "ar" ? "وجهات الجودة" : "Quality destinations",
    );
    expect(
      screen.getAllByText(
        language === "ar" ? "نفس الموقع الحالي" : "Same current location",
      ),
    ).toHaveLength(3);
    await act(async () => {});
  },
);
