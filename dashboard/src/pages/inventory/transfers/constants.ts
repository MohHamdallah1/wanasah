import type { TransferPurpose, TransferStatus } from "./types";

export const TRANSFER_STATUSES: TransferStatus[] = [
  "DRAFT",
  "PENDING",
  "IN_TRANSIT",
  "ACCEPTED",
  "REJECTED",
  "POSTED",
  "CANCELLED",
];

export const STATUS_META: Record<
  TransferStatus,
  { label: string; className: string }
> = {
  DRAFT: { label: "inventoryTransfers.DRAFT", className: "bg-slate-100 text-slate-600" },
  PENDING: { label: "inventoryTransfers.PENDING", className: "bg-amber-50 text-amber-700" },
  IN_TRANSIT: { label: "inventoryTransfers.IN_TRANSIT", className: "bg-blue-50 text-blue-700" },
  ACCEPTED: { label: "inventoryTransfers.ACCEPTED", className: "bg-cyan-50 text-cyan-700" },
  REJECTED: { label: "inventoryTransfers.REJECTED", className: "bg-red-50 text-red-700" },
  POSTED: { label: "inventoryTransfers.POSTED", className: "bg-emerald-50 text-emerald-700" },
  CANCELLED: { label: "inventoryTransfers.CANCELLED", className: "bg-slate-100 text-slate-500" },
};

export const isTransferStatus = (value: unknown): value is TransferStatus =>
  typeof value === "string" &&
  TRANSFER_STATUSES.includes(value as TransferStatus);

export const TRANSFER_PURPOSES: TransferPurpose[] = ["REPLENISHMENT", "ROUTE_LOAD", "ROUTE_RETURN", "WAREHOUSE_BALANCING", "RETURN_TO_VENDOR", "QUARANTINE", "RECALL_RETURN", "DISPOSAL"];
export const isTransferPurpose = (value: unknown): value is TransferPurpose => typeof value === "string" && TRANSFER_PURPOSES.includes(value as TransferPurpose);
