import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VehicleForm } from "./VehicleForm";

let direction: "rtl" | "ltr" = "rtl";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => direction },
  }),
}));

afterEach(() => {
  direction = "rtl";
});

describe("VehicleForm frozen V1 contract", () => {
  it("allows any nonnegative next oil-change mileage independently of current mileage", () => {
    const onSubmit = vi.fn();
    render(<VehicleForm onCancel={() => undefined} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.plate/), { target: { value: "12-34567" } });
    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.mileage/), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextOilChange/), { target: { value: "50" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ current_mileage: 100, next_oil_change: 50 });
  });

  it("uses required stars without optional/default badge clutter and keeps create mileage explicit", () => {
    render(<VehicleForm onCancel={() => undefined} onSubmit={() => undefined} />);

    const plate = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.plate/) as HTMLInputElement;
    const mileage = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.mileage/) as HTMLInputElement;
    const type = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.type/) as HTMLInputElement;
    const oil = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextOilChange/) as HTMLInputElement;
    const license = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.licenseExpiry/) as HTMLInputElement;
    const nextMaintenance = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextMaintenanceDate/) as HTMLInputElement;
    const status = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.maintenance/) as HTMLSelectElement;

    expect(plate.required).toBe(true);
    expect(plate.getAttribute("aria-required")).toBe("true");
    expect(mileage.required).toBe(true);
    expect(mileage.getAttribute("aria-required")).toBe("true");
    expect(mileage.value).toBe("");
    expect(type.required).toBe(false);
    expect(oil.required).toBe(false);
    expect(license.required).toBe(false);
    expect(nextMaintenance.required).toBe(false);
    expect(status.required).toBe(false);
    expect(status.value).toBe("Active");
    expect(screen.getByText("representativesVehicles.vehicles.form.requiredHint")).toBeTruthy();
    expect(screen.queryByText("representativesVehicles.vehicles.form.badges.optional")).toBeNull();
    expect(screen.queryByText("representativesVehicles.vehicles.form.badges.default")).toBeNull();
    expect(screen.getAllByText("*")).toHaveLength(3);
  });

  it("accepts a past next-maintenance date without changing maintenance status", () => {
    const onSubmit = vi.fn();
    render(<VehicleForm onCancel={() => undefined} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.plate/), { target: { value: "12-34567" } });
    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.mileage/), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextMaintenanceDate/), { target: { value: "2020-01-02" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      next_maintenance_date: "2020-01-02",
      maintenance_status: "Active",
    });
  });

  it("clears an existing next-maintenance date with explicit null", () => {
    const onSubmit = vi.fn();
    const vehicle = {
      id: 4, plate_number: "44-44444", vehicle_type: null, current_mileage: 500,
      next_oil_change: null, license_expiry_date: null, next_maintenance_date: "2026-12-01",
      maintenance_status: "Active" as const, is_active: true, version: 2, custody_ready: true,
    };
    render(<VehicleForm vehicle={vehicle} onCancel={() => undefined} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextMaintenanceDate/), { target: { value: "" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({ next_maintenance_date: null });
  });

  it("requires a fresh maintenance schedule before a maintained vehicle returns to service", async () => {
    const onSubmit = vi.fn();
    const vehicle = {
      id: 9, plate_number: "99-99999", vehicle_type: null, current_mileage: 900,
      next_oil_change: null, license_expiry_date: null, next_maintenance_date: "2000-01-02",
      maintenance_status: "In_Maintenance" as const, is_active: true, version: 3, custody_ready: true,
    };
    render(<VehicleForm vehicle={vehicle} onCancel={() => undefined} onSubmit={onSubmit} />);

    const nextMaintenance = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextMaintenanceDate/) as HTMLInputElement;
    fireEvent.change(screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.maintenance/), { target: { value: "Active" } });

    expect(nextMaintenance.value).toBe("");
    expect(nextMaintenance.getAttribute("min")).toBeTruthy();
    expect(screen.getByText("representativesVehicles.vehicles.form.returnToServiceScheduleHint")).toBeTruthy();

    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("representativesVehicles.vehicles.form.returnToServiceScheduleRequired")).toBeTruthy();

    fireEvent.change(nextMaintenance, { target: { value: "2099-01-02" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({
      next_maintenance_date: "2099-01-02",
      maintenance_status: "Active",
    });
  });

  it("submits an edited vehicle with Enter from an input field", () => {
    const onSubmit = vi.fn();
    const vehicle = {
      id: 12, plate_number: "12-12000", vehicle_type: "Van", current_mileage: 800,
      next_oil_change: 1200, license_expiry_date: null, next_maintenance_date: "2026-12-01",
      maintenance_status: "Active" as const, is_active: true, version: 4, custody_ready: true,
    };
    render(<VehicleForm vehicle={vehicle} onCancel={() => undefined} onSubmit={onSubmit} />);

    const type = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.type/) as HTMLInputElement;
    fireEvent.change(type, { target: { value: "Truck" } });
    fireEvent.keyDown(type, { key: "Enter", code: "Enter" });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({ vehicle_type: "Truck" });
  });

  it("submits an edited vehicle with Enter from the maintenance selector", () => {
    const onSubmit = vi.fn();
    const vehicle = {
      id: 13, plate_number: "13-13000", vehicle_type: "Van", current_mileage: 800,
      next_oil_change: 1200, license_expiry_date: null, next_maintenance_date: "2026-12-01",
      maintenance_status: "Active" as const, is_active: true, version: 4, custody_ready: true,
    };
    render(<VehicleForm vehicle={vehicle} onCancel={() => undefined} onSubmit={onSubmit} />);

    const status = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.maintenance/) as HTMLSelectElement;
    fireEvent.change(status, { target: { value: "In_Maintenance" } });
    fireEvent.keyDown(status, { key: "Enter", code: "Enter" });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({ maintenance_status: "In_Maintenance" });
  });

  it("keeps the compact form phone-first and locale-directed", () => {
    const { container, rerender } = render(<VehicleForm onCancel={() => undefined} onSubmit={() => undefined} />);
    expect(container.querySelector("form")?.getAttribute("dir")).toBe("rtl");
    expect(container.querySelector("form")).toHaveAttribute("novalidate");
    const oil = screen.getByLabelText(/representativesVehicles\.vehicles\.fields\.nextOilChange/) as HTMLInputElement;
    expect(oil.getAttribute("dir")).toBe("rtl");
    expect(container.querySelector(".grid")?.className).toContain("sm:grid-cols-2");
    fireEvent.change(oil, { target: { value: "1500" } });
    expect(oil.getAttribute("dir")).toBe("ltr");
    expect(oil).toHaveClass("text-right");
    direction = "ltr";
    rerender(<VehicleForm onCancel={() => undefined} onSubmit={() => undefined} />);
    expect(container.querySelector("form")?.getAttribute("dir")).toBe("ltr");
  });
});
