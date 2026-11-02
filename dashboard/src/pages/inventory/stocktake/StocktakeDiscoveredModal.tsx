import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useTranslation } from "react-i18next";
import { STOCKTAKE_STOCK_STATUSES, type StocktakeStockStatus } from "../inventoryUtils";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { parseCycleProductPage, getErrorMessage } from "./parsers";
import { buildDiscoveredRow, parseDiscoveredBatches, type DiscoveredBatch, type DiscoveredRow } from "./discoveredContract";
import { useStocktakeUiCopy } from "./uiCopy";
import type { CycleProductOption, StocktakeAuthFetch } from "./types";

interface Props {
  open: boolean;
  sessionId: string | null;
  authenticatedFetch: StocktakeAuthFetch;
  onClose: () => void;
  onAdd: (row: DiscoveredRow) => boolean;
}

export function StocktakeDiscoveredModal({ open, sessionId, authenticatedFetch, onClose, onAdd }: Props) {
  const { copy, dir } = useStocktakeUiCopy();
  const { t } = useTranslation();
  const text = copy.discovered;
  const [productSearch, setProductSearch] = useState("");
  const [batchSearch, setBatchSearch] = useState("");
  const [debouncedProductSearch, setDebouncedProductSearch] = useState("");
  const [debouncedBatchSearch, setDebouncedBatchSearch] = useState("");
  const [products, setProducts] = useState<CycleProductOption[]>([]);
  const [batches, setBatches] = useState<DiscoveredBatch[]>([]);
  const [productCursor, setProductCursor] = useState<string | null>(null);
  const [batchCursor, setBatchCursor] = useState<string | null>(null);
  const [product, setProduct] = useState<CycleProductOption | null>(null);
  const [batch, setBatch] = useState<DiscoveredBatch | null>(null);
  const [status, setStatus] = useState<StocktakeStockStatus>("QUARANTINED");
  const [quantity, setQuantity] = useState("");
  const [loading, setLoading] = useState(false);
  const requestGeneration = useRef(0);

  useEffect(() => {
    requestGeneration.current += 1;
    setProduct(null);
    setBatch(null);
    setProducts([]);
    setBatches([]);
    setProductSearch("");
    setBatchSearch("");
    setDebouncedProductSearch("");
    setDebouncedBatchSearch("");
    setProductCursor(null);
    setBatchCursor(null);
    setStatus("QUARANTINED");
    setQuantity("");
  }, [sessionId, open]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const clean = productSearch.trim();
      setDebouncedProductSearch(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [productSearch]);
  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const clean = batchSearch.trim();
      setDebouncedBatchSearch(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [batchSearch]);

  const fetchPage = useCallback(async (next: string | null, append: boolean) => {
    if (!open || !sessionId) return;
    const generation = ++requestGeneration.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (product) params.set("product_variant_id", String(product.id));
      const search = product ? debouncedBatchSearch : debouncedProductSearch;
      if (search) params.set("search", search);
      if (next) params.set("cursor", next);
      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/discovery-options?${params.toString()}`,
      );
      if (generation !== requestGeneration.current) return;
      if (product) {
        const page = parseDiscoveredBatches(raw, product.id);
        setBatches((prev) => append ? [...prev, ...page.items.filter(
          (item) => !prev.some((old) => old.id === item.id),
        )] : page.items);
        setBatchCursor(page.next_cursor);
      } else {
        const page = parseCycleProductPage(raw);
        setProducts((prev) => append ? [...prev, ...page.items.filter(
          (item) => !prev.some((old) => old.id === item.id),
        )] : page.items);
        setProductCursor(page.next_cursor);
      }
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      if (product) { setBatches([]); setBatchCursor(null); }
      else { setProducts([]); setProductCursor(null); }
      toast.error(getErrorMessage(error, text.discoveryError));
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [authenticatedFetch, debouncedBatchSearch, debouncedProductSearch, open, product, sessionId, text.discoveryError]);

  useEffect(() => {
    requestGeneration.current += 1;
    if (!open || !sessionId) return;
    if (product) { setBatches([]); setBatchCursor(null); }
    else { setProducts([]); setProductCursor(null); }
    void fetchPage(null, false);
    return () => { requestGeneration.current += 1; };
  }, [open, sessionId, product, fetchPage]);

  const chooseProduct = (value: CycleProductOption) => {
    setProduct(value);
    setBatch(null);
    setBatchSearch("");
    setDebouncedBatchSearch("");
  };
  const add = () => {
    if (!product || !batch || batch.product_variant_id !== product.id) {
      toast.error(text.invalid);
      return;
    }
    try {
      const discovered = buildDiscoveredRow(batch, status, quantity);
      if (onAdd(discovered)) {
        toast.success(text.added);
        setProduct(null);
        setBatch(null);
        setQuantity("");
        setStatus("QUARANTINED");
        onClose();
      } else toast.error(text.alreadyExists);
    } catch {
      toast.error(text.invalid);
    }
  };

  return <Modal
    isOpen={open && sessionId !== null}
    onClose={onClose}
    title={text.title}
    maxWidth="max-w-2xl"
    footer={<div dir={dir} className="flex gap-2 w-full">
      <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg">{text.cancel}</button>
      <button type="button" onClick={add} disabled={!batch || !quantity || loading}
        className="flex-1 px-4 py-2 rounded-lg bg-blue-600 text-white disabled:opacity-40">{text.save}</button>
    </div>}
  >
    <div dir={dir} className="space-y-4">
      <p className="text-sm text-slate-600">{text.hint}</p>
      {!product ? <>
        <label className="block text-sm font-bold" htmlFor="discovered-product">{text.chooseProduct}</label>
        <input id="discovered-product" autoFocus value={productSearch}
          onChange={(e) => setProductSearch(e.target.value)}
          placeholder={text.productSearch} className="w-full p-2 rounded-lg border" />
        <div className="max-h-48 overflow-y-auto border rounded-lg divide-y" role="group" aria-label={text.chooseProduct}>
          {products.map((item) => <button type="button" key={item.id} onClick={() => chooseProduct(item)}
            className="w-full p-3 text-start hover:bg-blue-50 focus-visible:ring-2 focus-visible:ring-blue-600">
            <span className="font-bold">{item.name}</span>
            <span className="block text-xs text-slate-500" dir="auto">{item.sku} · {item.base_uom_name}</span>
          </button>)}
          {!loading && products.length === 0 && <p className="p-3 text-sm text-slate-500">{text.noProducts}</p>}
        </div>
        {productCursor && <button type="button" disabled={loading} onClick={() => void fetchPage(productCursor, true)}
          className="border rounded-lg px-4 py-2">{text.loadMore}</button>}
      </> : <>
        <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 p-3">
          <strong>{product.name}</strong>
          <button type="button" onClick={() => { setProduct(null); setBatch(null); }} className="underline">{text.chooseProduct}</button>
        </div>
        <label className="block text-sm font-bold" htmlFor="discovered-batch">{text.chooseBatch}</label>
        <input id="discovered-batch" autoFocus value={batchSearch}
          onChange={(e) => setBatchSearch(e.target.value)}
          placeholder={text.batchSearch} className="w-full p-2 rounded-lg border" />
        <div className="max-h-44 overflow-y-auto border rounded-lg divide-y" role="group" aria-label={text.chooseBatch}>
          {batches.map((item) => <button type="button" key={item.id}
            aria-pressed={batch?.id === item.id} onClick={() => setBatch(item)}
            className={`w-full p-3 text-start focus-visible:ring-2 focus-visible:ring-blue-600 ${batch?.id === item.id ? "bg-blue-50" : "hover:bg-slate-50"}`}>
            <strong>{formatPublicBatchNumber(item.batch_number, t("inventoryLive.noLotSupplied"))}</strong>
            <span className="block text-xs text-slate-500">{item.expiry_date ?? "—"}</span>
            {(!item.is_active || item.disposition !== "RELEASED") &&
              <span className="block text-xs text-amber-700">{text.blocked}</span>}
          </button>)}
          {!loading && batches.length === 0 && <p className="p-3 text-sm text-slate-500">{text.noBatches}</p>}
        </div>
        {batchCursor && <button type="button" disabled={loading} onClick={() => void fetchPage(batchCursor, true)}
          className="border rounded-lg px-4 py-2">{text.loadMore}</button>}
        <p className="text-xs text-slate-500">{text.noUnknownLot}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-sm">{text.status}
            <select value={status} onChange={(e) => setStatus(e.target.value as StocktakeStockStatus)}
              className="block w-full mt-1 rounded-lg border p-2">
              {STOCKTAKE_STOCK_STATUSES.map((item) =>
                <option key={item} value={item}>{copy.stockStatuses[item]}</option>)}
            </select>
          </label>
          <label className="block text-sm">{text.quantity}
            <input type="text" inputMode="decimal" value={quantity}
              onChange={(e) => setQuantity(e.target.value.replace(/[^0-9.]/g, ""))}
              className="block w-full mt-1 rounded-lg border p-2" dir="ltr"
              placeholder={product.quantity_step} />
            <span className="text-xs text-slate-500">{product.base_uom_name} · {text.step}: {product.quantity_step}</span>
          </label>
        </div>
      </>}
      {loading && <p role="status" className="text-xs text-slate-500">{text.loading}</p>}
    </div>
  </Modal>;
}
