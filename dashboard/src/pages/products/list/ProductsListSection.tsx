import type {
  ComponentProps,
} from "react";

import { ProductsActiveFilters } from "@/pages/products/list/ProductsActiveFilters";
import { ProductsFiltersPanel } from "@/pages/products/list/ProductsFiltersPanel";
import { ProductsListResults } from "@/pages/products/list/ProductsListResults";
import { ProductsListToolbar } from "@/pages/products/list/ProductsListToolbar";
import { ProductsCatalogSummary } from "@/pages/products/list/ProductsCatalogSummary";

type Props = {
  summary?: ComponentProps<typeof ProductsCatalogSummary>;
  toolbar: Omit<
    ComponentProps<
      typeof ProductsListToolbar
    >,
    "filtersContent"
  >;
  activeFilters: ComponentProps<
    typeof ProductsActiveFilters
  >;
  filters: ComponentProps<
    typeof ProductsFiltersPanel
  >;
  results: ComponentProps<
    typeof ProductsListResults
  >;
};

export function ProductsListSection({
  summary,
  toolbar,
  activeFilters,
  filters,
  results,
}: Props) {
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="shrink-0 border-b border-slate-100 px-3 py-3 sm:px-4">
        <ProductsListToolbar
          {...toolbar}
          filtersContent={
            <ProductsFiltersPanel
              {...filters}
            />
          }
        />

        {summary ? <ProductsCatalogSummary {...summary} /> : null}

        <ProductsActiveFilters
          {...activeFilters}
        />
      </div>

      <ProductsListResults
        {...results}
      />
    </section>
  );
}
