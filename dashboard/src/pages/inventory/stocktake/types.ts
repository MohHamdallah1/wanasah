import type {
  StocktakeRow,
  StocktakeStockStatus,
} from "../inventoryUtils";
import type { Quantity } from "../quantity";

export type StocktakeType =
  | "FULL_COUNT"
  | "CYCLE_COUNT"
  | "VEHICLE_RECON";

export type StocktakeStatus =
  | "DRAFT"
  | "COUNTING"
  | "PENDING_REVIEW"
  | "RECOUNT_REQUIRED"
  | "APPROVED"
  | "POSTED"
  | "CANCELLED";

export type StocktakePhase =
  | "COUNTING"
  | "REVIEW"
  | "WAITING_INDEPENDENT";

export type StocktakeAuthFetch = (
  url: string,
  opts?: RequestInit
) => Promise<unknown>;

export interface CountSheetItem {
  product_variant_id: number;
  batch_id: number | null;
  stock_status: StocktakeStockStatus;
  product_name: string;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
  batch_number: string | null;
  expiry_date: string | null;
}

export interface ReviewLine {
  attempt_line_id: number;
  product_variant_id: number;
  batch_id: number | null;
  stock_status: StocktakeStockStatus;
  line_origin: "SNAPSHOT" | "DISCOVERED";
  product_name: string;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
  batch_number: string | null;
  expiry_date: string | null;
  expected_quantity: Quantity;
  actual_quantity: Quantity;
  variance_quantity: Quantity;
  notes?: string | null;
}

export interface ReviewAttempt {
  id: number;
  attempt_number: number;
  counted_by: number;
  counted_by_name: string;
  authorized_by: number | null;
  authorized_by_name: string | null;
  recount_of_attempt_id?: number | null;
  recount_reason: string | null;
  requires_independent_recount: boolean;
  submitted_at: string | null;
}

export interface StocktakeReview {
  session_id: number;
  reference_number: string;
  stocktake_type: StocktakeType;
  status: StocktakeStatus;
  location_id: number;
  independent_recount_satisfied: boolean;
  latest_attempt: ReviewAttempt;
  attempt_history: ReviewAttempt[];
  lines: ReviewLine[];
}

export interface StocktakeSessionSummary {
  id: number;
  reference_number: string;
  stocktake_type: StocktakeType;
  status: StocktakeStatus;
  location_id: number;
  scope_product_variant_id: number | null;
  scope_product_name: string | null;
  scope_batch_id: number | null;
  scope_batch_number: string | null;
  related_work_session_id: number | null;
  started_by: number;
  started_by_name: string;
  pending_independent_recount_required: boolean;
  snapshot_cutoff_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CycleProductOption {
  id: number;
  name: string;
  sku: string | null;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
}

export interface CycleProductCursorPage {
  items: CycleProductOption[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export interface CycleBatchOption {
  id: number;
  product_variant_id: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string;
  is_active: boolean;
}

export interface CycleBatchCursorPage {
  items: CycleBatchOption[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export interface StocktakeSessionContext {
  session_id: number;
  stocktake_type: StocktakeType;
  status: StocktakeStatus;
  location_id: number;
  related_work_session_id: number | null;
  source_location_id: number;
}

export interface VehicleReconCandidate {
  work_session_id: number;
  driver_id: number;
  driver_name: string;
  session_date: string;
  end_time: string;
  vehicle_id: number;
  vehicle_location_id: number;
  vehicle_location_name: string;
  vehicle_location_code: string;
  existing_stocktake_session_id: number | null;
  existing_stocktake_reference: string | null;
  existing_stocktake_status: StocktakeStatus | null;
}

export interface VehicleReconCandidateCursorPage {
  items: VehicleReconCandidate[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export interface StocktakeSessionCursorPage {
  items: StocktakeSessionSummary[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export type { StocktakeRow };
