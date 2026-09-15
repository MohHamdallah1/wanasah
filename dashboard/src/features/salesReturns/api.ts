import type {
  SalesReturnDetail,
  SalesReturnPage,
  SalesReturnSource,
} from "./contracts";

export type AuthFetch = (
  path: string,
  opts?: RequestInit
) => Promise<unknown>;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export async function fetchSalesReturnSource(
  authFetch: AuthFetch,
  visitId: number
): Promise<SalesReturnSource> {
  const value = await authFetch(`/sales-returns/source/${visitId}`);
  if (!isObject(value) || !Array.isArray(value.lines)) {
    throw new Error("عقد مصدر المرتجع غير صالح.");
  }
  return value as unknown as SalesReturnSource;
}

export async function fetchSalesReturns(
  authFetch: AuthFetch
): Promise<SalesReturnPage> {
  const value = await authFetch("/sales-returns?limit=50");
  if (!isObject(value) || !Array.isArray(value.items)) {
    throw new Error("عقد قائمة المرتجعات غير صالح.");
  }
  return value as unknown as SalesReturnPage;
}

export async function createSalesReturn(
  authFetch: AuthFetch,
  input: {
    original_sales_revision_id: number;
    reason: string;
    components: Array<{
      original_price_component_id: number;
      quantity: string;
    }>;
  }
): Promise<SalesReturnDetail> {
  const value = await authFetch("/sales-returns", {
    method: "POST",
    body: JSON.stringify({
      request_id: crypto.randomUUID(),
      ...input,
    }),
  });
  if (!isObject(value) || typeof value.id !== "number") {
    throw new Error("عقد إنشاء المرتجع غير صالح.");
  }
  return value as unknown as SalesReturnDetail;
}
