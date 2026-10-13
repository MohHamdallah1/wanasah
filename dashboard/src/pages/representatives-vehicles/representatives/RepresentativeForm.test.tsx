import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const translationState = vi.hoisted(() => ({
  direction: "rtl" as "rtl" | "ltr",
  language: "ar" as "ar" | "en",
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      if (key === "representativesVehicles.representatives.form.debtLimitPlaceholder") {
        return translationState.language === "ar" ? "مثال: 50.000" : "Example: 50.000";
      }
      return key;
    },
    i18n: { dir: () => translationState.direction },
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
  translationState.direction = "rtl";
  translationState.language = "ar";
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


  it("keeps a new disabled credit limit hidden and reveals an empty localized amount input", () => {
    const onSubmit = vi.fn();
    render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);

    expect(screen.queryByLabelText("representativesVehicles.representatives.fields.debtLimit")).toBeNull();
    fireEvent.click(screen.getByLabelText("representativesVehicles.representatives.fields.debtPermission"));

    const limit = screen.getByLabelText("representativesVehicles.representatives.fields.debtLimit") as HTMLInputElement;
    expect(limit.value).toBe("");
    expect(limit.placeholder).toBe("مثال: 50.000");
    fireEvent.change(limit, { target: { value: "50.000" } });
    expect(limit.value).toBe("50.000");
  });

  it("requires an explicit debt amount when a new representative enables credit", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.name"), { target: { value: "Ahmad" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.username"), { target: { value: "rep17" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.password"), { target: { value: "password8" } });
    fireEvent.click(screen.getByLabelText("representativesVehicles.representatives.fields.debtPermission"));
    fireEvent.submit(container.querySelector("form")!);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("representativesVehicles.representatives.form.debtRequired");
  });

  it("uses the safe disabled zero only in the new create payload", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.name"), { target: { value: "Ahmad" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.username"), { target: { value: "rep17" } });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.password"), { target: { value: "password8" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      can_allow_debt: false,
      max_debt_limit: "0.000",
    }), requestUuid));
  });

  it("preserves the stored edit value and selects it only for the first editing focus", () => {
    render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={vi.fn()} />);
    const limit = screen.getByLabelText("representativesVehicles.representatives.fields.debtLimit") as HTMLInputElement;
    expect(limit.value).toBe("25.500");

    fireEvent.focus(limit);
    expect(limit.value).toBe("25.500");
    expect(limit.selectionStart).toBe(0);
    expect(limit.selectionEnd).toBe("25.500".length);

    fireEvent.change(limit, { target: { value: "50.000" } });
    fireEvent.blur(limit);
    limit.setSelectionRange("50.000".length, "50.000".length);
    fireEvent.focus(limit);
    expect(limit.value).toBe("50.000");
    expect(limit.selectionStart).toBe("50.000".length);
    expect(limit.selectionEnd).toBe("50.000".length);
  });

  it("uses one logical field tree with RTL visual alignment and LTR value ordering", () => {
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={vi.fn()} />);
    const form = container.querySelector("form")!;
    const username = screen.getByLabelText("representativesVehicles.representatives.fields.username") as HTMLInputElement;
    const phone = screen.getByLabelText("representativesVehicles.representatives.fields.phone") as HTMLInputElement;

    expect(form.getAttribute("dir")).toBe("rtl");
    expect(username.dir).toBe("ltr");
    expect(phone.dir).toBe("ltr");
    expect(username.value).toBe("rep17");
    expect(phone.value).toBe("+962790000000");
    expect(username.className).toContain("text-right");
    expect(phone.className).toContain("text-right");
  });

  it("switches the same form structure to natural LTR alignment", () => {
    translationState.direction = "ltr";
    translationState.language = "en";
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={vi.fn()} />);
    const username = screen.getByLabelText("representativesVehicles.representatives.fields.username") as HTMLInputElement;
    const phone = screen.getByLabelText("representativesVehicles.representatives.fields.phone") as HTMLInputElement;

    expect(container.querySelector("form")?.getAttribute("dir")).toBe("ltr");
    expect(username.className).toContain("text-left");
    expect(phone.className).toContain("text-left");
    expect(username.value).toBe("rep17");
    expect(phone.value).toBe("+962790000000");
  });

  it("keeps the narrow-screen logical input order name, username, phone, password, then credit", () => {
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={vi.fn()} />);
    const controls = Array.from(container.querySelectorAll("input")).map((input) => input.id || input.type);
    expect(controls).toEqual([
      "representative-name",
      "representative-username",
      "representative-phone",
      "representative-password",
      "checkbox",
    ]);
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
