import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

import { representativesVehicles } from "../../../i18n/representativesVehicles";
import { RepresentativeForm } from "./RepresentativeForm";

const requestUuid = "11111111-1111-4111-8111-111111111111";

const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: "+962790000000",
  is_active: true,
  can_allow_debt: true,
  max_debt_limit: "25.500",
};

beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => requestUuid) });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RepresentativeForm", () => {
  it("submits the frozen create fields with an exact decimal debt value", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
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
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        full_name: "Ahmad Saleh",
        username: "rep17",
        phone_number: "+962790000000",
        password: "password8",
        can_allow_debt: true,
        max_debt_limit: "15.500",
      }, requestUuid);
    });
  });

  it("sends only materially changed edit fields", async () => {
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
      expect(onSubmit).toHaveBeenCalledWith({ full_name: "Ahmad S." }, requestUuid);
    });
  });

  it("sends explicit null when an existing phone number is cleared", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />,
    );

    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.phone"),
      { target: { value: "   " } },
    );
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ phone_number: null }, requestUuid);
    });
  });

  it("does not mutate when normalized edit values are unchanged", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />,
    );

    fireEvent.change(
      screen.getByLabelText("representativesVehicles.representatives.fields.name"),
      { target: { value: "  Ahmad Saleh  " } },
    );
    fireEvent.submit(container.querySelector("form")!);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(
      "representativesVehicles.representatives.form.noChanges",
    );
  });

  it("rejects a password that exceeds 72 UTF-8 bytes", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />,
    );

    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.name"), {
      target: { value: "Ahmad" },
    });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.username"), {
      target: { value: "rep17" },
    });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.password"), {
      target: { value: "ع".repeat(37) },
    });
    fireEvent.submit(container.querySelector("form")!);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(
      "representativesVehicles.representatives.form.passwordInvalid",
    );
  });

  it("reuses the same create request id when an unchanged submission is retried", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />,
    );

    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.name"), {
      target: { value: "Ahmad" },
    });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.username"), {
      target: { value: "rep17" },
    });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.password"), {
      target: { value: "password8" },
    });

    fireEvent.submit(container.querySelector("form")!);
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[0]?.[1]).toBe(requestUuid);
    expect(onSubmit.mock.calls[1]?.[1]).toBe(requestUuid);
  });

  it("retains the operation id across normalized retries but replaces it for a changed password", async () => {
    const nextUuid = "33333333-3333-4333-8333-333333333333";
    vi.mocked(crypto.randomUUID).mockReturnValueOnce(requestUuid).mockReturnValue(nextUuid);
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.name"), { target: { value: "Ahmad" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.username"), { target: { value: "rep17" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.password"), { target: { value: "password8" } });
    fireEvent.submit(container.querySelector("form")!);
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.name"), { target: { value: " Ahmad " } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1]).toEqual(onSubmit.mock.calls[0]);
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.password"), { target: { value: "different8" } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(3));
    expect(onSubmit.mock.calls[2]?.[1]).not.toBe(requestUuid);
  });

  it("disables credit authority without destroying the stored per-sale limit", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />,
    );

    expect(screen.getByLabelText("representativesVehicles.representatives.fields.debtLimit")).toBeTruthy();
    expect(screen.getByText("representativesVehicles.representatives.form.debtHint")).toBeTruthy();
    fireEvent.click(
      screen.getByLabelText("representativesVehicles.representatives.fields.debtPermission"),
    );

    expect(screen.queryByLabelText("representativesVehicles.representatives.fields.debtLimit")).toBeNull();
    expect(screen.queryByText("representativesVehicles.representatives.form.debtHint")).toBeNull();
    expect(screen.getByText("representativesVehicles.representatives.form.debtDisabled")).toBeTruthy();

    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ can_allow_debt: false }, requestUuid);
    });
  });
});


describe("Representative credit-limit clarity copy", () => {
  it("states explicitly in Arabic that the per-sale limit is not daily and does not reset automatically", () => {
    const helper = representativesVehicles.ar.representatives.form.debtHint;
    expect(helper).toContain("عملية بيع واحدة");
    expect(helper).toContain("ليس حدًا يوميًا");
    expect(helper).toContain("لا يتجدد تلقائيًا");
    expect(helper).toContain("سقف ذمة المحل");
  });

  it("states explicitly in English that the per-sale limit is not daily and does not reset automatically", () => {
    const helper = representativesVehicles.en.representatives.form.debtHint;
    expect(helper).toContain("single sale");
    expect(helper).toContain("not a daily limit");
    expect(helper).toContain("does not reset automatically");
    expect(helper).toContain("shop’s total credit limit");
  });
});
