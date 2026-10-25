import { fireEvent, render, screen } from "@testing-library/react";
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
  it("shows overdue maintenance in red, keeps ready-for-work green, and preserves Western digits", () => {
    render(<VehicleTable items={[base]} canManage onView={() => undefined} onLoad={() => undefined} onEdit={() => undefined} onLifecycle={() => undefined} onNoteAction={() => undefined} />);
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("representativesVehicles.vehicles.maintenance.active")).toHaveClass("bg-emerald-50", "text-emerald-700");
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.maintenanceOverdue/)).toHaveClass("text-rose-700");
    expect(screen.getByText("representativesVehicles.vehicles.fields.notes")).toBeTruthy();
    expect(screen.queryByText("representativesVehicles.vehicles.fields.custody")).toBeNull();
    expect(screen.getByText(/2000/)).toBeTruthy();
  });

  it("shows actionable overdue notes in red and preserves custody failure visibility", () => {
    render(<VehicleTable items={[{ ...base, next_maintenance_date: null, custody_ready: false, license_expiry_date: "2000-02-03", next_oil_change: 900 }]} canManage onView={() => undefined} onLoad={() => undefined} onEdit={() => undefined} onLifecycle={() => undefined} onNoteAction={() => undefined} />);
    expect(screen.getByText("representativesVehicles.vehicles.notes.custodyUnavailable")).toHaveClass("text-rose-700");
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.licenseExpired/)).toHaveClass("text-rose-700");
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.oilDue/)).toHaveClass("text-rose-700");
  });

  it("keeps future maintenance dates out of the notes column until they are due", () => {
    render(<VehicleTable items={[{ ...base, next_maintenance_date: "2999-01-01", next_oil_change: null }]} canManage onView={() => undefined} onLoad={() => undefined} onEdit={() => undefined} onLifecycle={() => undefined} onNoteAction={() => undefined} />);
    expect(screen.queryByText(/representativesVehicles\.vehicles\.notes\.maintenance/)).toBeNull();
  });

  it("keeps future oil-change targets out of the notes column until they are due", () => {
    render(<VehicleTable items={[{ ...base, next_maintenance_date: null, next_oil_change: 1500 }]} canManage onView={() => undefined} onLoad={() => undefined} onEdit={() => undefined} onLifecycle={() => undefined} onNoteAction={() => undefined} />);
    expect(screen.queryByText(/representativesVehicles\.vehicles\.notes\.oilDue/)).toBeNull();
    expect(screen.queryByText(/1,500/)).toBeNull();
  });
  it("makes due notes actionable without turning future reminders into noise", () => {
    const onNoteAction = vi.fn();
    render(
      <VehicleTable
        items={[{ ...base, next_maintenance_date: null, next_oil_change: 900 }]}
        canManage
        onView={() => undefined}
        onEdit={() => undefined}
        onLifecycle={() => undefined}
        onNoteAction={onNoteAction}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /representativesVehicles\.vehicles\.notes\.oilDue/ }));
    expect(onNoteAction).toHaveBeenCalledTimes(1);
    expect(onNoteAction.mock.calls[0]?.[1]).toMatchObject({ kind: "oil", mileage: 900 });
  });

});
