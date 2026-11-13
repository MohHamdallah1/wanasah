/** Precision-first matching for vehicle/draft pins in Route Launch.
 * The authenticated backend owns eligible warehouse product search.
 * Pinned vehicle stock must NOT bypass a typed product-name filter.
 */
export function normalizeLoadProductSearch(value: string): string {
  return value.normalize("NFKC")
    .toLowerCase()
    .replace(/[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/ؤ/g, "و")
    .replace(/ئ/g, "ي")
    .replace(/\s+/g, " ")
    .trim();
}

/** All query words must actually occur in the pinned SKU's known name.
 * No fuzzy synonyms: searching for noodles never shows an unrelated rice pin.
 */
export function matchesLoadPinnedProduct(name: string, query: string): boolean {
  const terms = normalizeLoadProductSearch(query).split(" ").filter(Boolean);
  if (!terms.length) return true;
  const productName = normalizeLoadProductSearch(name);
  return terms.every(term => productName.includes(term));
}
