import { parseLedgerPage, type LedgerEntry } from "./contracts";

export interface LedgerOperation {
  group_key: string;
  group_kind: "TRANSFER" | "STOCKTAKE" | "RECEIPT" | "MOVEMENT";
  operation_type: string;
  reference: string;
  latest_at: string;
  latest_movement_id: number;
  source_location_name: string | null;
  destination_location_name: string | null;
  latest_actor_name: string | null;
  stage_types: string[];
  movement_kinds: string[];
  movement_count: number;
  product_variant_count: number;
  batch_count: number;
  expandable: boolean;
  count_meaning: "POSTED_VARIANCE_MOVEMENTS" | "AUTHORIZED_IMMUTABLE_MOVEMENTS";
  stocktake_history: { session_id: number; warehouse_location_id: number; reference: string } | null;
}

export interface LedgerOperationPage {
  items: LedgerOperation[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface LedgerOperationChild extends LedgerEntry {
  matches_filter: boolean;
}

export interface LedgerChildPage {
  items: LedgerOperationChild[];
  next_cursor: string | null;
  has_more: boolean;
}

const obj = (x: unknown): Record<string, unknown> => {
  if (!x || typeof x !== "object" || Array.isArray(x)) throw new Error("LEDGER_OPERATION_INVALID");
  return x as Record<string, unknown>;
};
const integer = (v: unknown, min = 0): number => {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < min) throw new Error("LEDGER_OPERATION_INVALID");
  return v;
};
const word = (v: unknown, max = 1024): string => {
  if (typeof v !== "string" || v.length > max) throw new Error("LEDGER_OPERATION_INVALID");
  return v;
};
const nullableWord = (v: unknown, max = 200): string | null =>
  v === null || v === undefined ? null : word(v, max);
const words = (v: unknown): string[] => {
  if (!Array.isArray(v) || v.length > 200) throw new Error("LEDGER_OPERATION_INVALID");
  return v.map(x => word(x, 50));
};
const cursorPage = (raw: Record<string, unknown>) => {
  const next = raw.next_cursor;
  if (typeof raw.has_more !== "boolean" ||
    (next !== null && next !== undefined && (typeof next !== "string" || !next || next.length > 512)) ||
    (raw.has_more && typeof next !== "string")) {
    throw new Error("LEDGER_OPERATION_PAGE_INVALID");
  }
  return { has_more: raw.has_more, next_cursor: typeof next === "string" ? next : null };
};

export function parseLedgerOperationPage(raw: unknown): LedgerOperationPage {
  const data = obj(raw);
  if (data.type_filter_semantics !== "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED" ||
    !Array.isArray(data.items) || data.items.length > 200) throw new Error("LEDGER_OPERATION_PAGE_INVALID");
  const seen = new Set<string>();
  const items: LedgerOperation[] = data.items.map(value => {
    const item = obj(value);
    const key = word(item.group_key);
    if (!key || seen.has(key)) throw new Error("LEDGER_OPERATION_DUPLICATE");
    seen.add(key);
    const kind = word(item.group_kind, 20);
    if (kind !== "TRANSFER" && kind !== "STOCKTAKE" && kind !== "RECEIPT" && kind !== "MOVEMENT")
      throw new Error("LEDGER_OPERATION_INVALID");
    const meaning = word(item.count_meaning, 50);
    if (meaning !== "POSTED_VARIANCE_MOVEMENTS" && meaning !== "AUTHORIZED_IMMUTABLE_MOVEMENTS")
      throw new Error("LEDGER_OPERATION_INVALID");
    const history = item.stocktake_history === null || item.stocktake_history === undefined
      ? null : obj(item.stocktake_history);
    const at = word(item.latest_at, 64);
    if (!Number.isFinite(Date.parse(at)) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(at))
      throw new Error("LEDGER_OPERATION_INVALID");
    if (typeof item.expandable !== "boolean") throw new Error("LEDGER_OPERATION_INVALID");
    return {
      group_key: key, group_kind: kind, operation_type: word(item.operation_type, 50),
      reference: word(item.reference, 100), latest_at: at,
      latest_movement_id: integer(item.latest_movement_id, 1),
      source_location_name: nullableWord(item.source_location_name),
      destination_location_name: nullableWord(item.destination_location_name),
      latest_actor_name: nullableWord(item.latest_actor_name, 120),
      stage_types: words(item.stage_types), movement_kinds: words(item.movement_kinds),
      movement_count: integer(item.movement_count, 1),
      product_variant_count: integer(item.product_variant_count, 1),
      batch_count: integer(item.batch_count),
      expandable: item.expandable, count_meaning: meaning,
      stocktake_history: history ? {
        session_id: integer(history.session_id, 1),
        warehouse_location_id: integer(history.warehouse_location_id, 1),
        reference: word(history.reference, 100),
      } : null,
    };
  });
  return { items, ...cursorPage(data) };
}

export function parseLedgerOperationChildPage(raw: unknown, groupKey: string): LedgerChildPage {
  const data = obj(raw);
  if (data.group_key !== groupKey || !Array.isArray(data.items)) throw new Error("LEDGER_OPERATION_CHILD_INVALID");
  const page = parseLedgerPage({ ...data, total: null, available_types: [] });
  return {
    ...cursorPage(data),
    items: page.items.map((row, index) => {
      const original = obj(data.items[index]);
      if (typeof original.matches_filter !== "boolean") throw new Error("LEDGER_OPERATION_CHILD_INVALID");
      return { ...row, matches_filter: original.matches_filter as boolean };
    }),
  };
}

export function buildLedgerOperationUrl(input: {
  locationId: number; cursor?: string | null; search?: string;
  referenceType?: string; referenceId?: string; groupKey?: string; limit?: number;
}) {
  const path = input.groupKey
    ? `/warehouse/ledger/operations/${encodeURIComponent(input.groupKey)}/movements/cursor`
    : "/warehouse/ledger/operations/cursor";
  const query = new URLSearchParams({
    location_id: String(input.locationId),
    limit: String(input.limit ?? 20),
  });
  if (input.cursor) query.set("cursor", input.cursor);
  if (input.referenceId) {
    query.set("reference_id", input.referenceId);
    if (input.referenceType) query.set("reference_type", input.referenceType);
  } else {
    if ((input.search ?? "").trim().length >= 2) query.set("search", input.search!.trim());
    if (input.referenceType && input.referenceType !== "ALL") query.set("reference_type", input.referenceType);
  }
  return `${path}?${query.toString()}`;
}
