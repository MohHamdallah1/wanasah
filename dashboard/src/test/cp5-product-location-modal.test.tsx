import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const locale = vi.hoisted(() => ({ language: "ar", direction: "rtl" as "rtl" | "ltr" }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => `${locale.language}:${key}`,
    i18n: {
      language: locale.language,
      resolvedLanguage: locale.language,
      dir: () => locale.direction,
    },
  }),
}));

vi.mock("@/features/inventory/productLocations/ProductLocationManager", () => ({
  ProductLocationManager: () => (
    <button type="button">manager-focus-target</button>
  ),
}));

import { ProductLocationsModal } from "@/pages/products/product-locations/ProductLocationsModal";

const variant = {
  id: 41,
  name: "Product 41",
} as never;

afterEach(() => cleanup());

describe("CP5 ProductLocation modal accessibility", () => {
  it("inherits RTL/LTR direction and restores the existing modal keyboard close path", () => {
    const onClose = vi.fn();
    locale.language = "ar";
    locale.direction = "rtl";
    const { rerender } = render(
      <ProductLocationsModal
        isOpen
        variant={variant}
        locations={[]}
        loading={false}
        loadError={false}
        candidateLocationsUnavailable={false}
        onClose={onClose}
        onRetry={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(document.querySelector(".app-modal")).toHaveAttribute("dir", "rtl");
    expect(screen.getByText(/ar:catalogLifecycle.assignments.title/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "manager-focus-target" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    locale.language = "en";
    locale.direction = "ltr";
    rerender(
      <ProductLocationsModal
        isOpen
        variant={variant}
        locations={[]}
        loading={false}
        loadError={false}
        candidateLocationsUnavailable={false}
        onClose={onClose}
        onRetry={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(document.querySelector(".app-modal")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText(/en:catalogLifecycle.assignments.title/)).toBeInTheDocument();
  });
});
