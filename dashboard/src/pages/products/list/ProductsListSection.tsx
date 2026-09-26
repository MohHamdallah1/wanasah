import type {
  ComponentProps,
} from "react";

import { ProductsFiltersPanel } from "@/pages/products/list/ProductsFiltersPanel";
import { ProductsListResults } from "@/pages/products/list/ProductsListResults";
import { ProductsListToolbar } from "@/pages/products/list/ProductsListToolbar";

type Props = {
  filtersOpen: boolean;
  toolbar: ComponentProps<
    typeof ProductsListToolbar
  >;
  filters: ComponentProps<
    typeof ProductsFiltersPanel
  >;
  results: ComponentProps<
    typeof ProductsListResults
  >;
};

export function ProductsListSection({
  filtersOpen,
  toolbar,
  filters,
  results,
}: Props) {
  return (
    <section className="mt-2 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="shrink-0 border-b border-slate-100 px-3 py-3 sm:px-4">
        <ProductsListToolbar
          {...toolbar}
        />

        {filtersOpen ? (
          <ProductsFiltersPanel
            {...filters}
          />
        ) : null}
      </div>

      <ProductsListResults
        {...results}
      />
    </section>
  );
}
