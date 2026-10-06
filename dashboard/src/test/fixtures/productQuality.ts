import { batchFocusPayload, batchSource } from "./batchFocus";

export const qualityBatch = (id: number, sources = [batchSource(11, "Warehouse A")]) => ({
  ...batchFocusPayload(sources), batch_id: id, batch_number: `LOT-${id}`, operational_hold: "RECALL",
});

const inventorySummary = (batches: ReturnType<typeof qualityBatch>[]) => {
  const locations = new Map<number, {
    location_id: number;
    location_name: string;
    location_type: "WAREHOUSE" | "VEHICLE";
    on_hand_quantity: number;
    reserved_quantity: number;
  }>();
  let totalOnHand = 0;
  let totalReserved = 0;
  const batchIds = new Set<number>();

  for (const batch of batches) {
    let batchHasStock = false;
    for (const source of batch.sources) {
      const onHand = source.statuses.reduce((sum, status) => sum + Number(status.on_hand_quantity), 0);
      const reserved = source.statuses.reduce((sum, status) => sum + Number(status.reserved_quantity), 0);
      if (onHand <= 0) continue;
      batchHasStock = true;
      totalOnHand += onHand;
      totalReserved += reserved;
      const existing = locations.get(source.location_id);
      if (existing) {
        existing.on_hand_quantity += onHand;
        existing.reserved_quantity += reserved;
      } else {
        locations.set(source.location_id, {
          location_id: source.location_id,
          location_name: source.location_name,
          location_type: source.location_type,
          on_hand_quantity: onHand,
          reserved_quantity: reserved,
        });
      }
    }
    if (batchHasStock) batchIds.add(batch.batch_id);
  }

  const ordered = [...locations.values()].sort((left, right) =>
    left.location_type.localeCompare(right.location_type)
    || left.location_name.localeCompare(right.location_name)
    || left.location_id - right.location_id,
  );

  return {
    total_on_hand_quantity: String(totalOnHand),
    total_reserved_quantity: String(totalReserved),
    batch_count: batchIds.size,
    source_count: ordered.length,
    locations_preview: ordered.slice(0, 8).map((location) => ({
      ...location,
      on_hand_quantity: String(location.on_hand_quantity),
      reserved_quantity: String(location.reserved_quantity),
    })),
    locations_truncated: ordered.length > 8,
  };
};

export const productQualityPage = (batches = [
  qualityBatch(41, [batchSource(11, "Warehouse A"), batchSource(13, "Vehicle 13", "VEHICLE")]),
  qualityBatch(42, [batchSource(12, "Warehouse C")]),
]) => ({
  product_variant_id: 118, variant_version: 9, operational_hold: "RECALL", base_uom_id: 7, base_uom_code: "EACH",
  inventory_summary: inventorySummary(batches),
  batches, next_cursor: null as number | null, has_more: false,
  ready_to_resume_sales: false, company_requirements_remaining: true,
});
