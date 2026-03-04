export interface Driver {
  id: string;
  name: string;
  avatar: string;
  status: "On Route" | "Returning" | "At Depot";
  route: string;
  totalCash: number;
  cashFromSales: number;
  cashFromDebts: number;
  soldCartons: number;
  remainingCartons: number;
  startedCartons: number;
  completedVisits: number;
  pendingVisits: number;
  startTime: string;
  authorized: boolean;
}

export const drivers: Driver[] = [
  {
    id: "1",
    name: "Ahmad Khalil",
    avatar: "AK",
    status: "On Route",
    route: "Amman Central",
    totalCash: 350.0,
    cashFromSales: 300.0,
    cashFromDebts: 50.0,
    soldCartons: 40,
    remainingCartons: 10,
    startedCartons: 50,
    completedVisits: 18,
    pendingVisits: 4,
    startTime: "06:30 AM",
    authorized: true,
  },
  {
    id: "2",
    name: "Omar Haddad",
    avatar: "OH",
    status: "On Route",
    route: "Zarqa East",
    totalCash: 275.5,
    cashFromSales: 225.5,
    cashFromDebts: 50.0,
    soldCartons: 32,
    remainingCartons: 18,
    startedCartons: 50,
    completedVisits: 14,
    pendingVisits: 8,
    startTime: "07:00 AM",
    authorized: true,
  },
  {
    id: "3",
    name: "Sami Nasser",
    avatar: "SN",
    status: "Returning",
    route: "Irbid North",
    totalCash: 490.0,
    cashFromSales: 420.0,
    cashFromDebts: 70.0,
    soldCartons: 48,
    remainingCartons: 2,
    startedCartons: 50,
    completedVisits: 22,
    pendingVisits: 0,
    startTime: "05:45 AM",
    authorized: true,
  },
  {
    id: "4",
    name: "Fadi Mansour",
    avatar: "FM",
    status: "At Depot",
    route: "Salt District",
    totalCash: 120.0,
    cashFromSales: 95.0,
    cashFromDebts: 25.0,
    soldCartons: 15,
    remainingCartons: 35,
    startedCartons: 50,
    completedVisits: 7,
    pendingVisits: 15,
    startTime: "08:00 AM",
    authorized: false,
  },
  {
    id: "5",
    name: "Rami Yousef",
    avatar: "RY",
    status: "On Route",
    route: "Aqaba South",
    totalCash: 410.25,
    cashFromSales: 350.25,
    cashFromDebts: 60.0,
    soldCartons: 38,
    remainingCartons: 12,
    startedCartons: 50,
    completedVisits: 16,
    pendingVisits: 6,
    startTime: "06:15 AM",
    authorized: true,
  },
];

export const fleetStats = {
  totalFleetCash: 1645.75,
  totalCompletedVisits: 77,
  totalPendingVisits: 33,
  activeDrivers: 4,
  totalDrivers: 5,
};
