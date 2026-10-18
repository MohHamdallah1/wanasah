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

it("shows the effective same-location default without setup writes", async () => {
  mocks.fetch.mockResolvedValue({ draft: null, published: null });

  render(<QualityHandlingDestinationsCard />);
  await screen.findByText("Effective default");

  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  expect(
    mocks.fetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/locations/manage"),
    ),
  ).toBe(false);
  expect(screen.getAllByText("Same current location")).toHaveLength(3);
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
  expect(mocks.fetch.mock.calls[0][1]).toBeUndefined();
});

it("renders an explicit published policy as read-only custom configuration", async () => {
  mocks.fetch.mockResolvedValue({
    draft: null,
    published: {
      id: 11,
      revision: 4,
      status: "PUBLISHED",
      validated_payload: {
        quarantine_location_id: 21,
        disposal_location_id: 22,
        vendor_return_staging_location_id: 23,
        allow_retiring_warehouse_balancing: false,
      },
    },
  });

  render(<QualityHandlingDestinationsCard />);
  await screen.findByText("Custom configuration active");

  expect(screen.getByText("Location #21")).toBeInTheDocument();
  expect(screen.getByText("Location #22")).toBeInTheDocument();
  expect(screen.getByText("Location #23")).toBeInTheDocument();
  expect(screen.queryByText("Same current location")).toBeNull();
  expect(screen.getByText(/read-only/)).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();

  // Opening/rendering the modal controller performs GET only and never
  // overwrites the legacy Published configuration.
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
  expect(mocks.fetch.mock.calls[0][1]).toBeUndefined();
});

it("labels mixed published policy fields truthfully per destination", async () => {
  mocks.fetch.mockResolvedValue({
    draft: null,
    published: {
      id: 12,
      revision: 5,
      status: "PUBLISHED",
      validated_payload: {
        quarantine_location_id: null,
        disposal_location_id: 32,
        vendor_return_staging_location_id: null,
        allow_retiring_warehouse_balancing: false,
      },
    },
  });

  render(<QualityHandlingDestinationsCard />);
  await screen.findByText("Custom configuration active");
  expect(screen.getAllByText("Same current location")).toHaveLength(2);
  expect(screen.getByText("Location #32")).toBeInTheDocument();
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
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
