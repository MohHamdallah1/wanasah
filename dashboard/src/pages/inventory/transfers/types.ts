import type { Quantity } from "../quantity";

export type TransferStatus =
  | "DRAFT"
  | "PENDING"
  | "IN_TRANSIT"
  | "ACCEPTED"
  | "REJECTED"
  | "POSTED"
  | "CANCELLED";

export type TransferDirection = "all" | "source" | "destination";
export type TransferAction = "receive" | "reject" | "cancel";

export interface WarehouseTransferListItem {
  id: number;
  reference_number: string;
  source_location_id: number;
  source_location_name: string;
  destination_location_id: number;
  destination_location_name: string;
  status: TransferStatus;
  dispatched_by: number;
  dispatched_by_name: string;
  received_by: number | null;
  received_by_name: string | null;
  cancelled_by: number | null;
  cancelled_by_name: string | null;
  line_count: number;
  total_quantity: Quantity;
  notes: string | null;
  decision_reason: string | null;
  created_at: string;
  updated_at: string;
  accepted_at: string | null;
  rejected_at: string | null;
  cancelled_at: string | null;
  posted_at: string | null;
}

export interface WarehouseTransferCursorPage {
  items: WarehouseTransferListItem[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export interface WarehouseTransferLine {
  id: number;
  product_variant_id: number;
  product_name: string;
  batch_id: number;
  batch_number: string;
  expiry_date: string;
  quantity: Quantity;
  uom_id: number;
  fefo_override_reason_id: number | null;
  fefo_overridden_by: number | null;
  fefo_override_note: string | null;
}

export interface WarehouseTransferDetail {
  transfer: WarehouseTransferListItem;
  lines: WarehouseTransferLine[];
}

export interface Props {
  locationId: number;
  onInventoryChanged: () => void | Promise<void>;
}


export type TransferCreateDirection = "outgoing" | "incoming";

export interface TransferLocationOption {
  id: number;
  name: string;
  code: string;
  location_type: "WAREHOUSE" | "VEHICLE";
  vehicle_id: number | null;
}

export interface TransferSourceInventoryItem {
  id: number;
  name: string;
  sku: string | null;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
  available_quantity: Quantity;
}

export interface TransferSourceInventoryPage {
  items: TransferSourceInventoryItem[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export type FefoMode = "auto" | "override";

export interface TransferOverrideReason {
  id: number;
  code: string;
  description: string;
}

export interface TransferOverrideBatch {
  id: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string;
  available_quantity: Quantity;
  is_fefo_head: boolean;
}

export interface TransferOverrideOptions {
  location_id: number;
  product_variant_id: number;
  fefo_batch_id: number | null;
  batches: TransferOverrideBatch[];
  reasons: TransferOverrideReason[];
}

export interface TransferDraftItem extends TransferSourceInventoryItem {
  draft_key: string;
  product_variant_id: number;
  quantity: string;
  fefo_mode: FefoMode;
  override_batch_id: number | null;
  override_reason_id: number | null;
  override_batch_available: Quantity | null;
}
