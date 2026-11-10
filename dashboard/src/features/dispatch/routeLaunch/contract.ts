import type { Quantity } from "@/lib/quantity";
import { parseQuantity } from "@/lib/quantity";

/** The canonical D07 server accepts this business intent plus one stable UUID.
 * No display labels, money values, auth tokens or mutable UI state are persisted.
 */
export type RouteLaunchIntent = {
  zone_id: number;
  driver_id: number;
  vehicle_id: number;
  source_location_id: number;
  inventory_base: Record<string, Quantity>;
  expected_inventory_base: Record<string, Quantity>;
};

export type RouteLaunchActor = {
  /** D10 canonical verified company:principal:backofficeUser scope. */
  actorScope: string;
  warehouseId: number;
  vehicleId: number;
};
export type RouteLaunchReceipt = {
  request_id: string;
  state: "COMMITTED";
  route_id: number;
  commercial_context: {
    commercial_context_id: number;
    price_publication_revision: number;
    tax_ruleset_version: number;
    rounding_policy_version: number;
    [field: string]: unknown;
  };
  message: string;
};
export type RouteLaunchOutcome =
  | { kind: "idle" | "unknown" | "blocked" | "conflict" | "busy" | "stale"; requestId?: string }
  | { kind: "committed"; requestId: string; receipt: RouteLaunchReceipt };

export type RouteLaunchLanguage = "ar" | "en";
export const routeLaunchText = (language: string, state: RouteLaunchOutcome["kind"]): string => {
  const ar: Record<RouteLaunchOutcome["kind"], string> = {
    idle: "لا توجد عملية إطلاق معلقة.",
    unknown: "لم يتأكد إطلاق المسار بعد. احتفظنا بالطلب الأصلي؛ يمكنك التحقق أو إعادة محاولته دون تكرار.",
    blocked: "انتهت الصلاحية أو تعذر التحقق من الحساب. لا يمكن متابعة العملية.",
    conflict: "توجد عملية إطلاق أصلية معلقة أو تغيّر الطلب. لا يمكن إنشاء طلب آخر قبل تسويتها.",
    busy: "عملية إطلاق أخرى جارية. لا يمكن إرسال طلب مكرر.",
    stale: "تغيّر الحساب أو نطاق الصلاحيات. تم تجاهل الرد القديم.",
    committed: "تم التحقق من إطلاق المسار الأصلي بنجاح.",
  };
  const en: typeof ar = {
    idle: "There is no pending route launch.",
    unknown: "Route launch is unconfirmed. Your original request is preserved; check or retry it without duplication.",
    blocked: "Your access has changed or cannot be verified. The operation is blocked.",
    conflict: "An original launch is pending or the request changed. Resolve it before starting another.",
    busy: "Another route launch is in progress. A duplicate cannot be sent.",
    stale: "Your account or access scope changed. The old response was ignored.",
    committed: "The original route launch was verified successfully.",
  };
  return (language.toLowerCase().startsWith("ar") ? ar : en)[state];
};

const pos = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const positiveId = (value: string | number): number => {
  if (typeof value === "number" && pos(value)) return value;
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value) || !pos(Number(value))) {
    throw new Error("D07_INVALID_BUSINESS_ID");
  }
  return Number(value);
};
const decimalMap = (raw: Record<string, Quantity>, field: string) => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("D07_INVALID_QUANTITIES");
  const result: Record<string, Quantity> = {};
  for (const variant of Object.keys(raw).sort((a, b) => Number(a) - Number(b))) {
    const id = positiveId(variant);
    const key = String(id);
    if (key in result) throw new Error("D07_DUPLICATE_VARIANT");
    result[key] = parseQuantity(raw[variant], field, { allowZero: true });
  }
  return result;
};

/** Normalize once BEFORE persisting. Never reconstruct a retry from live stock. */
export const routeLaunchIntent = (raw: {
  zone_id: string | number; driver_id: string | number;
  vehicle_id: string | number; source_location_id: string | number;
  inventory_base: Record<string, Quantity>;
  expected_inventory_base: Record<string, Quantity>;
}): RouteLaunchIntent => {
  const intent: RouteLaunchIntent = {
    zone_id: positiveId(raw.zone_id),
    driver_id: positiveId(raw.driver_id),
    vehicle_id: positiveId(raw.vehicle_id),
    source_location_id: positiveId(raw.source_location_id),
    inventory_base: decimalMap(raw.inventory_base, "inventory_base"),
    expected_inventory_base: decimalMap(raw.expected_inventory_base, "expected_inventory_base"),
  };
  if (!Object.values(intent.inventory_base).some(q => Number(q) > 0)) {
    throw new Error("D07_EMPTY_ROUTE_LOAD");
  }
  if (Object.keys(intent.inventory_base).some(id => !(id in intent.expected_inventory_base))) {
    throw new Error("D07_EXPECTED_STOCK_MISSING");
  }
  return intent;
};

export const routeLaunchScopeKey = ({ actorScope, warehouseId, vehicleId }: RouteLaunchActor): string => {
  if (!/^[1-9]\d*:[1-9]\d*:[1-9]\d*$/.test(actorScope) ||
      actorScope.split(":").some(part => !pos(Number(part))) ||
      !pos(warehouseId) || !pos(vehicleId)) throw new Error("D07_INVALID_ACTOR_SCOPE");
  // Identity, Warehouse and vehicle are a single canonical operating scope.
  return `wanasah:durable:v1:${actorScope}:dispatch-route-launch:v1:${warehouseId}:${vehicleId}`;
};
export const isRouteLaunchIntent = (candidate: unknown, actor: RouteLaunchActor): candidate is RouteLaunchIntent => {
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
  try {
    const raw = candidate as RouteLaunchIntent;
    const normalized = routeLaunchIntent(raw);
    return normalized.source_location_id === actor.warehouseId &&
      normalized.vehicle_id === actor.vehicleId &&
      JSON.stringify(normalized) === JSON.stringify(raw);
  } catch { return false; }
};

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const isOriginalRouteUuid = (id: unknown): id is string =>
  typeof id === "string" && uuid.test(id);

export function originalRouteReceipt(raw: unknown, requestId: string): RouteLaunchReceipt | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  if (row.state !== "COMMITTED" || row.request_id !== requestId ||
      !pos(row.route_id) || typeof row.message !== "string" ||
      !row.commercial_context || typeof row.commercial_context !== "object" ||
      Array.isArray(row.commercial_context)) return null;
  const context = row.commercial_context as Record<string, unknown>;
  if (!pos(context.commercial_context_id) || !pos(context.price_publication_revision) ||
      !pos(context.tax_ruleset_version) || !pos(context.rounding_policy_version)) return null;
  return row as RouteLaunchReceipt;
}

/** The GET response wraps the original immutable POST 201 receipt. */
export const routeLaunchReadback = (raw: unknown, requestId: string): RouteLaunchReceipt | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  if (row.request_id !== requestId || row.state !== "COMMITTED") return null;
  return originalRouteReceipt(row.response, requestId);
};
