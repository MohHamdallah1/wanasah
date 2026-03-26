export type TabId = "routes" | "zones";
export type ScheduleStatus = "overdue" | "soon" | "upcoming" | "future" | "today" | "null" | null;
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
  sessionEnded?: boolean; // +++ إضافة حالة الجلسة (للتراجع عن إنهاء العمل) +++
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
  zoneId: string;
  zoneName: string;
  shopId: string;
  shopName: string;
  driverId?: string;
  driverName?: string;
  productName: string;
  quantity: number;
  status: "pending" | "fulfilled";
  waitTime?: string;
  createdAt?: string;
}

export interface Zone {
  id: string;
  name: string;
  scheduleStatus: ScheduleStatus;
  frequency: string;
  visitDay: string;
  startDate: string;
  shopsCount?: number;
  calculatedStatus?: string;
  dateColor?: string;
}

export interface CustomSelectOption {
  id: string;
  label: string;
  scheduleStatus?: ScheduleStatus;
}
