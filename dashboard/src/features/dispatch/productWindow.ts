export type DispatchProductOption = {
  id: string;
  name: string;
};

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

export function positiveDispatchInventory(
  quantities: Record<string, number>,
): Record<string, number> {
  const result: Record<string, number> = {};

  for (const [productId, rawQuantity] of Object.entries(quantities)) {
    const quantity = Number(rawQuantity);
    if (!Number.isSafeInteger(quantity) || quantity <= 0) continue;
    result[productId] = quantity;
  }

  return result;
}

export function mergeDispatchProductWindow<T extends DispatchProductOption>(
  selected: T[],
  searched: T[],
): T[] {
  const seen = new Set<string>();
  const result: T[] = [];

  for (const product of [...selected, ...searched]) {
    if (seen.has(product.id)) continue;
    seen.add(product.id);
    result.push(product);
  }

  return result;
}
