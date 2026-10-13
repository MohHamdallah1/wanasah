import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

import { RepresentativeForm } from "./RepresentativeForm";

const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: "+962790000000",
  is_active: true,
  can_allow_debt: true,
  max_debt_limit: "25.500",
};

afterEach(() => {
  cleanup();
});

describe("RepresentativeForm", () => {
  it("submits the frozen create fields with an exact decimal debt value", async () => {
    const onSubmit = vi.fn();
    render(
      <RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />,
    );

    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.name"),
      { target: { value: "  Ahmad Saleh  " } },
    );
    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.username"),
      { target: { value: "rep17" } },
    );
    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.phone"),
      { target: { value: " +962790000000 " } },
    );
    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.password"),
      { target: { value: "password8" } },
    );
    fireEvent.click(
      screen.getByLabelText("representativesVehicles.representatives.fields.debtPermission"),
    );
    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.debtLimit"),
      { target: { value: "15.5" } },
    );
    fireEvent.submit(screen.getByRole("form", { hidden: true }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        full_name: "Ahmad Saleh",
        username: "rep17",
        phone_number: "+962790000000",
        password: "password8",
        can_allow_debt: true,
        max_debt_limit: "15.500",
      });
    });
  });

  it("edits profile fields without putting a password into the update payload", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <RepresentativeForm
        representative={representative}
        onCancel={() => undefined}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.queryByLabelText("representativesVehicles.representatives.fields.password")).toBeNull();
    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.name"),
      { target: { value: "Ahmad S." } },
    );
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        full_name: "Ahmad S.",
        username: "rep17",
        phone_number: "+962790000000",
        can_allow_debt: true,
        max_debt_limit: "25.500",
      });
    });
  });
});
