import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Vehicle } from "./contracts";
import { VehicleTable } from "./VehicleTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { date?: string; mileage?: string }) => values?.date ? `${key}: ${values.date}` : values?.mileage ? `${key}: ${values.mileage}` : key,
    i18n: { language: "ar" },
  }),
}));
vi.mock("./VehicleRowActions", () => ({
  VehicleRowActions: () => <button type="button">actions</button>,
}));

const base: Vehicle = {
  id: 1,
  plate_number: "12-34567",
  vehicle_type: "Van",
  current_mileage: 1000,
  next_oil_change: null,
  license_expiry_date: null,
  next_maintenance_date: "2000-01-02",
  maintenance_status: "Active",
  is_active: true,
  version: 1,
  custody_ready: true,
};

describe("VehicleTable operator notes", () => {
  it("shows an overdue business date compactly without changing maintenance state and keeps Western digits", () => {
    render(<VehicleTable items={[base]} canManage onEdit={() => undefined} onLifecycle={() => undefined} />);
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("representativesVehicles.vehicles.maintenance.active")).toBeTruthy();
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.maintenanceOverdue/)).toBeTruthy();
    expect(screen.getByText("representativesVehicles.vehicles.fields.notes")).toBeTruthy();
    expect(screen.queryByText("representativesVehicles.vehicles.fields.custody")).toBeNull();
    expect(screen.getByText(/2000/)).toBeTruthy();
  });

  it("shows actionable operator notes and preserves custody failure visibility", () => {
    render(<VehicleTable items={[{ ...base, next_maintenance_date: null, custody_ready: false, license_expiry_date: "2000-02-03", next_oil_change: 900 }]} canManage onEdit={() => undefined} onLifecycle={() => undefined} />);
    expect(screen.getByText("representativesVehicles.vehicles.notes.custodyUnavailable")).toBeTruthy();
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.licenseExpired/)).toBeTruthy();
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.oilDue/)).toBeTruthy();
  });
});
