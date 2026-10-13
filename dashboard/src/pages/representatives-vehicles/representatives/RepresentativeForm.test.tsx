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
const field = {
  name: "representativesVehicles.representatives.fields.name",
  username: "representativesVehicles.representatives.fields.username",
  phone: "representativesVehicles.representatives.fields.phone",
  password: "representativesVehicles.representatives.fields.password",
  confirm: "representativesVehicles.representatives.fields.confirmPassword",
  debtPermission: "representativesVehicles.representatives.fields.debtPermission",
  debtLimit: "representativesVehicles.representatives.fields.debtLimit",
} as const;

const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: "+962790000000",
  is_active: true,
  can_allow_debt: true,
  max_debt_limit: "25.500",
};

function fillCreateBasics(options: {
  name?: string;
  username?: string;
  phone?: string;
  password?: string;
  confirm?: string;
} = {}) {
  const name = options.name ?? "Ahmad";
  const username = options.username ?? "rep17";
  const phone = options.phone ?? "+962790000000";
  const password = options.password ?? "password8";
  const confirm = options.confirm ?? password;
  fireEvent.change(screen.getByLabelText(field.name), { target: { value: name } });
  fireEvent.change(screen.getByLabelText(field.username), { target: { value: username } });
  fireEvent.change(screen.getByLabelText(field.phone), { target: { value: phone } });
  fireEvent.change(screen.getByLabelText(field.password), { target: { value: password } });
  fireEvent.change(screen.getByLabelText(field.confirm), { target: { value: confirm } });
}

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
  it("submits required create fields, excludes confirmation, and preserves exact debt", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics({ name: "  Ahmad Saleh  ", phone: " +962790000000 " });
    fireEvent.click(screen.getByLabelText(field.debtPermission));
    fireEvent.change(screen.getByLabelText(field.debtLimit), { target: { value: "15.5" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const input = onSubmit.mock.calls[0]?.[0];
    expect(input).toEqual({
      full_name: "Ahmad Saleh",
      username: "rep17",
      phone_number: "+962790000000",
      password: "password8",
      can_allow_debt: true,
      max_debt_limit: "15.500",
    });
    expect(input).not.toHaveProperty("confirm_password");
    expect(onSubmit.mock.calls[0]?.[1]).toBe(requestUuid);
  });

  it.each([
    [field.name, "", "representativesVehicles.representatives.form.required"],
    [field.username, "", "representativesVehicles.representatives.form.required"],
    [field.phone, "   ", "representativesVehicles.representatives.form.phoneRequired"],
    [field.password, "", "representativesVehicles.representatives.form.passwordInvalid"],
    [field.confirm, "", "representativesVehicles.representatives.form.confirmRequired"],
  ])("blocks create when %s is blank", (label, value, errorKey) => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics();
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(errorKey);
  });

  it("blocks mismatched create password confirmation without clearing either field", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics({ password: "password8", confirm: "different8" });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("representativesVehicles.representatives.form.passwordMismatch");
    expect((screen.getByLabelText(field.password) as HTMLInputElement).value).toBe("password8");
    expect((screen.getByLabelText(field.confirm) as HTMLInputElement).value).toBe("different8");
  });

  it("keeps confirmation out of request identity", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics();
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText(field.confirm), { target: { value: "temporary-mismatch" } });
    fireEvent.change(screen.getByLabelText(field.confirm), { target: { value: "password8" } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1]?.[1]).toBe(onSubmit.mock.calls[0]?.[1]);
    expect(onSubmit.mock.calls[1]?.[0]).not.toHaveProperty("confirm_password");
  });

  it("requires phone when editing and never sends null to clear it", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText(field.phone), { target: { value: "   " } });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("representativesVehicles.representatives.form.phoneRequired");
  });

  it("sends only materially changed edit fields and never shows password fields", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />);
    expect(screen.queryByLabelText(field.password)).toBeNull();
    expect(screen.queryByLabelText(field.confirm)).toBeNull();
    fireEvent.change(screen.getByLabelText(field.name), { target: { value: "Ahmad S." } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ full_name: "Ahmad S." }, requestUuid));
  });

  it("saves edited representative name username and trimmed phone", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText(field.name), { target: { value: "Ahmad Updated" } });
    fireEvent.change(screen.getByLabelText(field.username), { target: { value: "rep-updated" } });
    fireEvent.change(screen.getByLabelText(field.phone), { target: { value: " 0791111111 " } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      full_name: "Ahmad Updated",
      username: "rep-updated",
      phone_number: "0791111111",
    }, requestUuid));
  });

  it.each([
    ["50.000", "50"],
    ["50.500", "50.5"],
    ["50.005", "50.005"],
  ])("shows stored edit debt %s as %s without mutating normalized meaning", (stored, displayed) => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm representative={{ ...representative, max_debt_limit: stored }} onCancel={() => undefined} onSubmit={onSubmit} />);
    const limit = screen.getByLabelText(field.debtLimit) as HTMLInputElement;
    expect(limit.value).toBe(displayed);
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("representativesVehicles.representatives.form.noChanges");
  });

  it("does not mutate when normalized edit values are unchanged", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText(field.name), { target: { value: "  Ahmad Saleh  " } });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("representativesVehicles.representatives.form.noChanges");
  });

  it("rejects a password that exceeds 72 UTF-8 bytes", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    const password = "ع".repeat(37);
    fillCreateBasics({ password, confirm: password });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("representativesVehicles.representatives.form.passwordInvalid");
  });

  it("accepts exactly 72 UTF-8 bytes", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    const password = `${"a".repeat(70)}م`;
    expect(new TextEncoder().encode(password).byteLength).toBe(72);
    fillCreateBasics({ password, confirm: password });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it.each(["محمدمحمد", "password8", "محمدAbc123!"])("accepts password policy sample %s", async (password) => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics({ password, confirm: password });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("reuses the same create request id when an unchanged submission is retried", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics();
    fireEvent.submit(container.querySelector("form")!);
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[0]?.[1]).toBe(requestUuid);
    expect(onSubmit.mock.calls[1]?.[1]).toBe(requestUuid);
  });

  it("retains operation id across normalized retries but replaces it for a changed password", async () => {
    const nextUuid = "33333333-3333-4333-8333-333333333333";
    vi.mocked(crypto.randomUUID).mockReturnValueOnce(requestUuid).mockReturnValue(nextUuid);
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics();
    fireEvent.submit(container.querySelector("form")!);
    fireEvent.change(screen.getByLabelText(field.name), { target: { value: " Ahmad " } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1]).toEqual(onSubmit.mock.calls[0]);
    fireEvent.change(screen.getByLabelText(field.password), { target: { value: "different8" } });
    fireEvent.change(screen.getByLabelText(field.confirm), { target: { value: "different8" } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(3));
    expect(onSubmit.mock.calls[2]?.[1]).toBe(nextUuid);
  });

  it("keeps disabled credit limit hidden and reveals an empty localized input", () => {
    render(<RepresentativeForm onCancel={() => undefined} onSubmit={vi.fn()} />);
    expect(screen.queryByLabelText(field.debtLimit)).toBeNull();
    fireEvent.click(screen.getByLabelText(field.debtPermission));
    const limit = screen.getByLabelText(field.debtLimit) as HTMLInputElement;
    expect(limit.value).toBe("");
    expect(limit.placeholder).toBe("مثال: 50.000");
  });

  it("requires explicit debt amount when credit is enabled", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics();
    fireEvent.click(screen.getByLabelText(field.debtPermission));
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("representativesVehicles.representatives.form.debtRequired");
  });

  it("uses safe disabled zero only in create payload", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={onSubmit} />);
    fillCreateBasics();
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      can_allow_debt: false,
      max_debt_limit: "0.000",
    }), requestUuid));
  });

  it("preserves stored edit debt and selects only first focus", () => {
    render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={vi.fn()} />);
    const limit = screen.getByLabelText(field.debtLimit) as HTMLInputElement;
    expect(limit.value).toBe("25.5");
    fireEvent.focus(limit);
    expect(limit.selectionStart).toBe(0);
    expect(limit.selectionEnd).toBe("25.5".length);
    fireEvent.change(limit, { target: { value: "50.000" } });
    fireEvent.blur(limit);
    limit.setSelectionRange("50.000".length, "50.000".length);
    fireEvent.focus(limit);
    expect(limit.selectionStart).toBe("50.000".length);
  });

  it("uses semantic required and username helper association", () => {
    render(<RepresentativeForm onCancel={() => undefined} onSubmit={vi.fn()} />);
    for (const label of [field.name, field.username, field.phone, field.password, field.confirm]) {
      const input = screen.getByLabelText(label) as HTMLInputElement;
      expect(input.required).toBe(true);
      expect(input.getAttribute("aria-required")).toBe("true");
    }
    expect(screen.getByLabelText(field.username)).toHaveAttribute("aria-describedby", "representative-username-hint");
    expect(screen.getByText("representativesVehicles.representatives.form.usernameHint")).toBeTruthy();
  });

  it("uses one logical field tree with RTL alignment and LTR Latin values", () => {
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={vi.fn()} />);
    const username = screen.getByLabelText(field.username) as HTMLInputElement;
    const phone = screen.getByLabelText(field.phone) as HTMLInputElement;
    expect(container.querySelector("form")?.getAttribute("dir")).toBe("rtl");
    expect(username.dir).toBe("ltr");
    expect(phone.dir).toBe("ltr");
    expect(username.className).toContain("text-right");
  });

  it("renders an Arabic username RTL without changing its value", () => {
    render(<RepresentativeForm representative={{ ...representative, username: "مندوب_12" }} onCancel={() => undefined} onSubmit={vi.fn()} />);
    const username = screen.getByLabelText(field.username) as HTMLInputElement;
    expect(username.dir).toBe("rtl");
    expect(username.value).toBe("مندوب_12");
  });

  it("switches the same form structure to natural LTR alignment", () => {
    translationState.direction = "ltr";
    translationState.language = "en";
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={vi.fn()} />);
    expect(container.querySelector("form")?.getAttribute("dir")).toBe("ltr");
    expect(screen.getByLabelText(field.username).className).toContain("text-left");
    expect(screen.getByLabelText(field.phone).className).toContain("text-left");
  });

  it("keeps mobile logical order name username phone password confirm then credit", () => {
    const { container } = render(<RepresentativeForm onCancel={() => undefined} onSubmit={vi.fn()} />);
    const controls = Array.from(container.querySelectorAll("input")).map((input) => input.id || input.type);
    expect(controls).toEqual([
      "representative-name",
      "representative-username",
      "representative-phone",
      "representative-password",
      "representative-confirm-password",
      "checkbox",
    ]);
  });

  it("disables credit authority without destroying stored per-sale limit", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<RepresentativeForm representative={representative} onCancel={() => undefined} onSubmit={onSubmit} />);
    expect(screen.getByLabelText(field.debtLimit)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(field.debtPermission));
    expect(screen.queryByLabelText(field.debtLimit)).toBeNull();
    expect(screen.getByText("representativesVehicles.representatives.form.debtDisabled")).toBeTruthy();
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ can_allow_debt: false }, requestUuid));
  });
});

describe("Representative final form copy", () => {
  it("keeps accepted credit semantics in Arabic and English", () => {
    const ar = representativesVehicles.ar.representatives.form.debtHint;
    const en = representativesVehicles.en.representatives.form.debtHint;
    expect(ar).toContain("عملية بيع واحدة");
    expect(ar).toContain("ليس حدًا يوميًا");
    expect(ar).toContain("لا يتجدد تلقائيًا");
    expect(ar).toContain("سقف ذمة المحل");
    expect(en).toContain("single sale");
    expect(en).toContain("not a daily limit");
    expect(en).toContain("does not reset automatically");
  });

  it("has required phone and equal-status Arabic username copy", () => {
    expect(representativesVehicles.ar.representatives.form.phoneRequired).toBe("أدخل رقم هاتف المندوب.");
    expect(representativesVehicles.en.representatives.form.phoneRequired).toBe("Enter the representative’s phone number.");
    expect(representativesVehicles.ar.representatives.form.usernameHint).toContain("أحرفًا عربية أو إنجليزية");
    expect(representativesVehicles.en.representatives.form.usernameHint).toContain("Arabic or Latin letters");
  });
});
