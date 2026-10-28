import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDispatchProductSearch, type DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { mergeDispatchProductWindow } from "@/features/dispatch/productWindow";
import { ProductSearchControls } from "./ProductSearchControls";
import { InfiniteProductScroll } from "./InfiniteProductScroll";

export function ShortageProductPicker({ scope, selected, drafted, onSelect }: {
  scope: string | null; selected: { id: string; name: string } | null;
  drafted: { productId: string; productName: string }[]; onSelect: (id: string, name: string) => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const page = useDispatchProductSearch("/dispatch/products?purpose=SHORTAGE", search, scope, "SHORTAGE");
  const pins: DispatchDiscoveryProduct[] = [...drafted.map((row) => ({ id: row.productId, name: row.productName, load: null })),
    ...(selected ? [{ ...selected, load: null }] : [])];
  return <div className="space-y-2">
    <ProductSearchControls search={search} onChange={setSearch} page={page} />
    <div className="space-y-1">{mergeDispatchProductWindow(pins, page.items).map((product) =>
      <button type="button" key={product.id} aria-label={t("dispatchProductSearch.select", { name: product.name })}
        aria-pressed={selected?.id === product.id} onClick={() => onSelect(product.id, product.name)} className="block w-full rounded-lg border border-slate-200 bg-white p-2 text-start text-slate-800 hover:bg-slate-50">
        {product.name}
      </button>)}</div>
    <InfiniteProductScroll page={page} />
  </div>;
}
