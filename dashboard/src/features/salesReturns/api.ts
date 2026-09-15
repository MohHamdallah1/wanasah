import type {
  SalesReturnDetail,
  SalesReturnEligibleSourcePage,
  SalesReturnPage,
  SalesReturnSource,
} from "./contracts";

export type AuthFetch = (
  path: string,
  opts?: RequestInit
) => Promise<unknown>;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export interface ReturnableSalesQuery {
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  beforeRevisionId?: number | null;
  limit?: number;
}

export async function fetchReturnableSales(
  authFetch: AuthFetch,
  query: ReturnableSalesQuery = {}
): Promise<SalesReturnEligibleSourcePage> {
  const params = new URLSearchParams();
  params.set("limit", String(query.limit ?? 50));

  const search = query.search?.trim();
  if (search) params.set("search", search);
  if (query.dateFrom) params.set("date_from", query.dateFrom);
  if (query.dateTo) params.set("date_to", query.dateTo);
  if (query.beforeRevisionId) {
    params.set("before_revision_id", String(query.beforeRevisionId));
  }

  const value = await authFetch(
    `/sales-returns/sources?${params.toString()}`
  );
  if (
    !isObject(value) ||
    !Array.isArray(value.items) ||
    typeof value.has_more !== "boolean" ||
    !(
      value.next_cursor === null ||
      typeof value.next_cursor === "number"
    )
  ) {
    throw new Error("عقد المبيعات القابلة للمرتجع غير صالح.");
  }
  return value as unknown as SalesReturnEligibleSourcePage;
}

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
