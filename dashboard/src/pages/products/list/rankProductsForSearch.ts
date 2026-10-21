import type { SimpleProduct } from "@/pages/products/contracts";

const normalize = (value: string | null | undefined) =>
  (value ?? "").trim().toLocaleLowerCase();

const scoreProduct = (item: SimpleProduct, query: string) => {
  const name = normalize(item.name);
  const sku = normalize(item.sku);
  const unitBarcode = normalize(item.unit_barcode);
  const packageBarcode = normalize(item.package_barcode);
  const family = normalize(item.family_name);

  if (name === query) return 0;
  if (sku === query || unitBarcode === query || packageBarcode === query) return 1;
  if (name.startsWith(query)) return 2;
  if (sku.startsWith(query) || unitBarcode.startsWith(query) || packageBarcode.startsWith(query)) return 3;
  if (family === query || family.startsWith(query)) return 4;
  return 5;
};

export function rankProductsForSearch(
  items: SimpleProduct[],
  search: string,
): SimpleProduct[] {
  const query = normalize(search);
  if (!query || items.length < 2) return items;

  return items
    .map((item, index) => ({
      item,
      index,
      score: scoreProduct(item, query),
    }))
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map(({ item }) => item);
}