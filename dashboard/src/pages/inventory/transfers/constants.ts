import type { TransferStatus } from "./types";

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
  DRAFT: { label: "مسودة", className: "bg-slate-100 text-slate-600" },
  PENDING: { label: "معلقة", className: "bg-amber-50 text-amber-700" },
  IN_TRANSIT: { label: "في الطريق", className: "bg-blue-50 text-blue-700" },
  ACCEPTED: { label: "مقبولة", className: "bg-cyan-50 text-cyan-700" },
  REJECTED: { label: "مرفوضة", className: "bg-red-50 text-red-700" },
  POSTED: { label: "مستلمة", className: "bg-emerald-50 text-emerald-700" },
  CANCELLED: { label: "ملغاة", className: "bg-slate-100 text-slate-500" },
};

export const isTransferStatus = (value: unknown): value is TransferStatus =>
  typeof value === "string" &&
  TRANSFER_STATUSES.includes(value as TransferStatus);
