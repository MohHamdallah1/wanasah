export type ProductWarehouseFilterOption = {
  id: number;
  name: string;
  code: string;
};

type WarehouseFilterPage = {
  items: ProductWarehouseFilterOption[];
  has_more: boolean;
};

const invalid = (): never => {
  const error = new Error("WAREHOUSE_FILTER_RESPONSE_INVALID") as Error & {
    code: string;
  };
  error.code = "WAREHOUSE_FILTER_RESPONSE_INVALID";
  throw error;
};

export function parseWarehouseFilterPage(raw: unknown): WarehouseFilterPage {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  if (!Array.isArray(row.items) || typeof row.has_more !== "boolean") return invalid();
  if (row.items.length > 200) return invalid();

  const seen = new Set<number>();
  const items = row.items.map((rawItem) => {
    if (!rawItem || typeof rawItem !== "object" || Array.isArray(rawItem)) return invalid();
    const item = rawItem as Record<string, unknown>;
    if (
      typeof item.id !== "number" ||
      !Number.isSafeInteger(item.id) ||
      item.id <= 0 ||
      seen.has(item.id) ||
      typeof item.name !== "string" ||
      !item.name.trim() ||
      item.name.length > 200 ||
      typeof item.code !== "string" ||
      !item.code.trim() ||
      item.code.length > 100
    ) return invalid();
    seen.add(item.id);
    return { id: item.id, name: item.name.trim(), code: item.code.trim() };
  });

  return { items, has_more: row.has_more };
}
