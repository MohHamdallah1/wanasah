import { batchFocusPayload, batchSource } from "./batchFocus";

export const qualityBatch = (id: number, sources = [batchSource(11, "Warehouse A")]) => ({
  ...batchFocusPayload(sources), batch_id: id, batch_number: `LOT-${id}`, operational_hold: "RECALL",
});

export const productQualityPage = (batches = [
  qualityBatch(41, [batchSource(11, "Warehouse A"), batchSource(13, "Vehicle 13", "VEHICLE")]),
  qualityBatch(42, [batchSource(12, "Warehouse C")]),
]) => ({
  product_variant_id: 118, variant_version: 9, operational_hold: "RECALL", base_uom_id: 7, base_uom_code: "EACH",
  batches, next_cursor: null as number | null, has_more: false,
  ready_to_resume_sales: false, company_requirements_remaining: true,
});
