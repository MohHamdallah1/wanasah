// +++ الكي الجراحي: إضافة تبويب الإطلاق لتطابق الـ UI +++
export type TabId = "routes" | "zones" | "launch";
export type ScheduleStatus = "overdue" | "today" | "upcoming" | "null";
export type RouteStatus = "waiting" | "active" | "postponed";

export interface PendingRoute {
  id: string;
  zoneId: string;
  zoneName: string;
  driverId: string;
  driverName: string;
  vehicleId: string;
  shopsRemaining: number;
  status: RouteStatus;
  sessionEnded: boolean; // +++ إضافة حالة الجلسة (للتراجع عن إنهاء العمل) +++
  sessionBound: boolean;
  can_execute: boolean;
}

export interface Shop {
  id: string;
  name: string;
  owner: string;
  phone: string;
  mapLink: string;
  zoneId: string;
  initialDebt: number;
  maxDebtLimit: number;
  sequence: number;
  archived: boolean;
}

export interface Shortage {
  id: string;
  productId: string;
  zoneId: string;
  zoneName: string;
  shopId: string;
  shopName: string;
  driverId?: string;
  driverName?: string;
  productName: string;
  quantity: number;
  status: "pending" | "fulfilled";
  waitTime?: string | null;
  createdAt?: string | null;
}

export interface Zone {
  id: string;
  name: string;
  scheduleStatus: ScheduleStatus;
  frequency: string;
  visitDay: string;
  startDate: string;
  intervalDays: number | null;
  shopsCount?: number;
  calculatedStatus?: string;
  dateColor?: string;
}

export interface CustomSelectOption {
  id: string;
  label: string;
  scheduleStatus?: ScheduleStatus;
}

// +++ الدرع المعماري: تعريف بيانات المصافحات (Transfers) لتمكين المشرف من تتبعها +++
export interface RouteTransfer {
  transfer_id: number;
  product_name: string;
  delta_cartons: number;
  delta_packs: number;
  status: "pending" | "accepted" | "rejected" | "cancelled";
  created_at: string | null;
  batch_id: string;
  can_force_cancel: boolean;
}
