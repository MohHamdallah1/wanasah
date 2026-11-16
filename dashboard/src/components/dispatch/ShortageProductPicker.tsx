import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useDispatchProductSearch } from "@/features/dispatch/useDispatchProductSearch";
import { ProductSearchControls } from "./ProductSearchControls";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";

/** Fast add-to-draft is presentation only; eligibility comes from the server's SHORTAGE discovery. */
export function ShortageProductPicker({
  scope, drafted, onAdd, disabled = false,
}: {
  scope: string | null;
  drafted: { productId: string; productName: string; quantity: number }[];
  onAdd: (id: string, name: string) => void;
  disabled?: boolean;
}) {
  const { i18n } = useTranslation();
  const [search, setSearch] = useState("");
  const page = useDispatchProductSearch(
    disabled ? null : "/dispatch/products?purpose=SHORTAGE",
    search, scope, "SHORTAGE",
  );
  const counts = new Map(drafted.map(item => [item.productId, item.quantity]));
  const t = (key: Parameters<typeof dispatchUiText>[1], vars?: Record<string, string | number>) =>
    dispatchUiText(i18n.language, key, vars ?? {});
  return <section className="min-w-0 space-y-3" aria-label={t("shortageQuickProductsStep")}>
    <div className="flex items-center gap-2 text-sm font-bold text-slate-800">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1e87bb] text-xs text-white">2</span>
      <span>{t("shortageQuickProductsStep")}</span>
    </div>
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <ProductSearchControls search={search} onChange={setSearch} page={page} enabled={!disabled}/>
      {!page.loading && !page.error && search.trim().length >= 2 && (
        <div className="mt-3 max-h-64 divide-y divide-slate-100 overflow-y-auto">
          {page.items.map(product => {
            const count = counts.get(product.id) ?? 0;
            return <button type="button" key={product.id} disabled={disabled}
              onClick={() => onAdd(product.id, product.name)}
              aria-label={t("shortageQuickAddOne", { product: product.name })}
              className="flex min-h-12 w-full min-w-0 items-center gap-3 px-2 py-2 text-start hover:bg-blue-50 focus-visible:bg-blue-50 disabled:opacity-50">
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{product.name}</span>
              {count > 0 && <span className="rounded-lg bg-blue-50 px-2 py-1 text-xs font-bold text-blue-800"
                aria-label={t("shortageQuickInDraft", { count })}>{t("shortageQuickInDraft", { count })}</span>}
              <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#1e87bb] text-white">
                <Plus className="h-4 w-4"/>
              </span>
            </button>;
          })}
        </div>
      )}
    </div>
  </section>;
}
