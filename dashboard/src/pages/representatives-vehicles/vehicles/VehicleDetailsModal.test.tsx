import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Vehicle } from "./contracts";
import { VehicleDetailsModal } from "./VehicleDetailsModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { date?: string; mileage?: string }) =>
      values?.date ? `${key}: ${values.date}` : values?.mileage ? `${key}: ${values.mileage}` : key,
    i18n: { language: "ar" },
  }),
}));

vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children, title }: { isOpen: boolean; children: React.ReactNode; title: string }) =>
    isOpen ? <div><h2>{title}</h2>{children}</div> : null,
}));

const vehicle: Vehicle = {
  id: 8,
  plate_number: "10-22222",
  vehicle_type: "Van",
  current_mileage: 12000,
  next_oil_change: 15000,
  license_expiry_date: "2999-12-31",
  next_maintenance_date: "2999-11-30",
  maintenance_status: "Active",
  is_active: true,
  version: 1,
  custody_ready: true,
};

describe("VehicleDetailsModal", () => {
  it("shows complete scheduled vehicle information even when it is not yet a current note", () => {
    render(<VehicleDetailsModal vehicle={vehicle} open onOpenChange={vi.fn()} />);

    expect(screen.getByText("representativesVehicles.vehicles.details.title")).toBeTruthy();
    expect(screen.getByText("10-22222")).toBeTruthy();
    expect(screen.getByText("Van")).toBeTruthy();
    expect(screen.getByText("12,000")).toBeTruthy();
    expect(screen.getByText("15,000")).toBeTruthy();
    expect(screen.getByText("representativesVehicles.vehicles.details.noNotes")).toBeTruthy();
  });

  it("shows only current actionable notes in its notes section", () => {
    render(
      <VehicleDetailsModal
        vehicle={{ ...vehicle, current_mileage: 16000, license_expiry_date: "2000-01-01" }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.oilDue/)).toBeTruthy();
    expect(screen.getByText(/representativesVehicles\.vehicles\.notes\.licenseExpired/)).toBeTruthy();
  });
});
