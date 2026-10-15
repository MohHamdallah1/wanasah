import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Vehicle } from "./contracts";
import { VehicleQuickUpdateModal } from "./VehicleQuickUpdateModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => "rtl", language: "ar" },
  }),
}));

const vehicle: Vehicle = {
  id: 7,
  plate_number: "12-34567",
  vehicle_type: "Van",
  current_mileage: 15000,
  next_oil_change: 15000,
  license_expiry_date: "2020-01-01",
  next_maintenance_date: "2020-01-01",
  maintenance_status: "Active",
  is_active: true,
  version: 3,
  custody_ready: true,
};

describe("VehicleQuickUpdateModal", () => {
  it("records the next oil-change target through the focused one-field flow", () => {
    const onSubmit = vi.fn();
    render(
      <VehicleQuickUpdateModal
        vehicle={vehicle}
        kind="oil"
        open
        onClose={() => undefined}
        onSubmit={onSubmit}
      />,
    );

    const input = screen.getByLabelText("representativesVehicles.vehicles.fields.nextOilChange");
    fireEvent.change(input, { target: { value: "20000" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({ next_oil_change: 20000 });
  });


  it("rejects an oil-change target that is equal to or below the current mileage", () => {
    const onSubmit = vi.fn();
    render(
      <VehicleQuickUpdateModal
        vehicle={vehicle}
        kind="oil"
        open
        onClose={() => undefined}
        onSubmit={onSubmit}
      />,
    );

    const input = screen.getByLabelText("representativesVehicles.vehicles.fields.nextOilChange");
    fireEvent.change(input, { target: { value: "14000" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("representativesVehicles.vehicles.quickActions.oilMustBeFuture")).toBeTruthy();
  });

  it("can finish maintenance and schedule the next date in one action", () => {
    const onSubmit = vi.fn();
    render(
      <VehicleQuickUpdateModal
        vehicle={{ ...vehicle, maintenance_status: "In_Maintenance" }}
        kind="maintenance"
        open
        onClose={() => undefined}
        onSubmit={onSubmit}
      />,
    );

    const input = screen.getByLabelText("representativesVehicles.vehicles.fields.nextMaintenanceDate");
    fireEvent.change(input, { target: { value: "2099-01-01" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({
      next_maintenance_date: "2099-01-01",
      maintenance_status: "Active",
    });
  });
});
