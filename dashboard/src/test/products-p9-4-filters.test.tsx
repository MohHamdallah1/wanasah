import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import {
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  readFileSync,
} from "node:fs";

vi.mock(
  "react-i18next",
  () => ({
    useTranslation: () => ({
      t: (
        key: string,
        options?: {
          filter?: string;
        },
      ) =>
        options?.filter
          ? `${key}:${options.filter}`
          : key,
    }),
  }),
);

import { ProductsActiveFilters } from "../pages/products/list/ProductsActiveFilters";

const read = (relativePath: string) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products P9.4 active filters", () => {
  it("keeps active filters visible and removes each through the existing callbacks", () => {
    const onFamilyFilterChange = vi.fn();
    const onLifecycleFilterChange = vi.fn();
    const onClearControls = vi.fn();

    render(
      <ProductsActiveFilters
        familyFilterId="7"
        familyFilterName="Family 7"
        lifecycleFilter="ACTIVE"
        trackingTypeFilter=""
        compatibilityFilter=""
        barcodeFilter=""
        canViewPricing
        priceFilter=""
        lotFilter=""
        expiryFilter=""
        sortBy="id"
        sortDir="asc"
        defaultSortBy="id"
        defaultSortDir="asc"
        onFamilyFilterChange={
          onFamilyFilterChange
        }
        onLifecycleFilterChange={
          onLifecycleFilterChange
        }
        onTrackingTypeFilterChange={
          vi.fn()
        }
        onCompatibilityFilterChange={
          vi.fn()
        }
        onBarcodeFilterChange={
          vi.fn()
        }
        onPriceFilterChange={
          vi.fn()
        }
        onLotFilterChange={vi.fn()}
        onExpiryFilterChange={vi.fn()}
        onSortByChange={vi.fn()}
        onSortDirChange={vi.fn()}
        onClearControls={onClearControls}
      />,
    );

    expect(
      screen.getByText(
        "products.filters.family: Family 7",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "products.filters.lifecycle: products.details.lifecycleModes.ACTIVE",
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name:
          "products.filters.remove:products.filters.family: Family 7",
      }),
    );
    expect(
      onFamilyFilterChange,
    ).toHaveBeenCalledWith("");

    fireEvent.click(
      screen.getByRole("button", {
        name:
          "products.filters.clear",
      }),
    );
    expect(
      onClearControls,
    ).toHaveBeenCalledTimes(1);
  });

  it("shows sort override as one removable state and restores the configured default", () => {
    const onSortByChange = vi.fn();
    const onSortDirChange = vi.fn();

    render(
      <ProductsActiveFilters
        familyFilterId=""
        familyFilterName=""
        lifecycleFilter=""
        trackingTypeFilter=""
        compatibilityFilter=""
        barcodeFilter=""
        canViewPricing={false}
        priceFilter=""
        lotFilter=""
        expiryFilter=""
        sortBy="name"
        sortDir="desc"
        defaultSortBy="id"
        defaultSortDir="asc"
        onFamilyFilterChange={vi.fn()}
        onLifecycleFilterChange={vi.fn()}
        onTrackingTypeFilterChange={
          vi.fn()
        }
        onCompatibilityFilterChange={
          vi.fn()
        }
        onBarcodeFilterChange={
          vi.fn()
        }
        onPriceFilterChange={vi.fn()}
        onLotFilterChange={vi.fn()}
        onExpiryFilterChange={vi.fn()}
        onSortByChange={onSortByChange}
        onSortDirChange={onSortDirChange}
        onClearControls={vi.fn()}
      />,
    );

    const label =
      "products.filters.sortBy: products.filters.sortFields.name · products.filters.descending";

    expect(
      screen.getByText(label),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name:
          `products.filters.remove:${label}`,
      }),
    );

    expect(
      onSortByChange,
    ).toHaveBeenCalledWith("id");
    expect(
      onSortDirChange,
    ).toHaveBeenCalledWith("asc");
  });

  it("keeps the filter panel as a dense workspace region instead of another nested card", () => {
    const panel = read(
      "../pages/products/list/ProductsFiltersPanel.tsx",
    );
    const section = read(
      "../pages/products/list/ProductsListSection.tsx",
    );

    expect(panel).toContain(
      "border-t border-slate-100 pt-3",
    );
    expect(panel).toContain(
      "xl:grid-cols-5",
    );
    expect(panel).not.toContain(
      "rounded-2xl border border-slate-100 bg-slate-50/70 p-3",
    );
    expect(section).toContain(
      "<ProductsActiveFilters",
    );
  });
});
