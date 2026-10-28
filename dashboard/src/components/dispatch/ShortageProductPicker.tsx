import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDispatchProductSearch, type DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { mergeDispatchProductWindow } from "@/features/dispatch/productWindow";
import { ProductSearchControls } from "./ProductSearchControls";

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
    <div className="max-h-48 overflow-auto">{mergeDispatchProductWindow(pins, page.items).map((product) =>
      <button type="button" key={product.id} aria-label={t("dispatchProductSearch.select", { name: product.name })}
        aria-pressed={selected?.id === product.id} onClick={() => onSelect(product.id, product.name)} className="block w-full rounded border p-2 text-start">
        {product.name}
      </button>)}</div>
  </div>;
}
