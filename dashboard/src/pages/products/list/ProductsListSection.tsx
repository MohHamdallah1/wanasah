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
    <section className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-[22px] border border-white/70 bg-white/85 shadow-sm backdrop-blur-xl sm:rounded-[26px]">
      <div className="shrink-0 border-b border-slate-100 p-4">
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
