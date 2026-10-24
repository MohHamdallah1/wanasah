export type DispatchProductOption = {
  id: string;
  name: string;
};

export const DISPATCH_PRODUCT_WINDOW_LIMIT = 80;

const searchTokens = (search: string): string[] =>
  search
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/)
    .filter(Boolean);

export function boundedDispatchProductSearch(
  products: DispatchProductOption[],
  search: string,
  limit = DISPATCH_PRODUCT_WINDOW_LIMIT,
): DispatchProductOption[] {
  if (limit <= 0) return [];

  const tokens = searchTokens(search);
  const result: DispatchProductOption[] = [];

  for (const product of products) {
    if (tokens.length) {
      const name = product.name.toLocaleLowerCase();
      if (!tokens.every((token) => name.includes(token))) {
        continue;
      }
    }

    result.push(product);
    if (result.length >= limit) break;
  }

  return result;
}

export function selectedDispatchProducts(
  productsById: Map<string, DispatchProductOption>,
  quantities: Record<string, number>,
): DispatchProductOption[] {
  const result: DispatchProductOption[] = [];

  for (const [productId, quantity] of Object.entries(quantities)) {
    if (!(Number(quantity) > 0)) continue;
    const product = productsById.get(productId);
    if (product) result.push(product);
  }

  return result;
}

export function mergeDispatchProductWindow(
  selected: DispatchProductOption[],
  searched: DispatchProductOption[],
): DispatchProductOption[] {
  const seen = new Set<string>();
  const result: DispatchProductOption[] = [];

  for (const product of [...selected, ...searched]) {
    if (seen.has(product.id)) continue;
    seen.add(product.id);
    result.push(product);
  }

  return result;
}
