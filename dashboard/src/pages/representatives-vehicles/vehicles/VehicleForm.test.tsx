import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VehicleForm } from "./VehicleForm";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => "rtl" },
  }),
}));

describe("VehicleForm frozen V1 contract", () => {
  it("allows any nonnegative next oil-change mileage independently of current mileage", () => {
    const onSubmit = vi.fn();
    render(<VehicleForm onCancel={() => undefined} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText("representativesVehicles.vehicles.fields.plate"), { target: { value: "12-34567" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.vehicles.fields.mileage"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.vehicles.fields.nextOilChange"), { target: { value: "50" } });
    fireEvent.submit(screen.getByRole("button", { name: "common.save" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ current_mileage: 100, next_oil_change: 50 });
  });
});
