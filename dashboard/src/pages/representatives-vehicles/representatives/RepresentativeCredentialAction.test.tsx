import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  reset: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({ t: (key: string) => key }),
  };
});
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("@/lib/apiErrors", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/apiErrors")>();
  return {
    ...actual,
    apiErrorMessage: (_error: unknown, fallback: string) => fallback,
  };
});
vi.mock("./api", () => ({ resetRepresentativeCredentials: mocks.reset }));
vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children, footer }: { isOpen: boolean; children: ReactNode; footer?: ReactNode }) =>
    isOpen ? <div>{children}{footer}</div> : null,
}));

import { RepresentativeCredentialAction } from "./RepresentativeCredentialAction";

const requestUuid = "22222222-2222-4222-8222-222222222222";
const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: null,
  is_active: true,
  can_allow_debt: false,
  max_debt_limit: "0.000",
};

const changePassword = (password: string) => {
  for (const key of ["newPassword", "confirmPassword"]) {
    fireEvent.change(screen.getByLabelText(`representativesVehicles.representatives.fields.${key}`), { target: { value: password } });
  }
};
const enterPassword = (password: string) => {
  fireEvent.click(screen.getByText("representativesVehicles.representatives.credentials.reset"));
  changePassword(password);
};
const readyAfterCalls = async (count: number) => {
  await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(count));
  await waitFor(() => expect(screen.getByText("common.confirm")).not.toBeDisabled());
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "11");
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => requestUuid) });
  mocks.reset.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe("RepresentativeCredentialAction", () => {
  it.each(["ع".repeat(37), "😀".repeat(4)])("rejects a reset password outside canonical character/UTF-8 bounds", (password) => {
    render(<RepresentativeCredentialAction representative={representative} allowed />);

    fireEvent.click(screen.getByText("representativesVehicles.representatives.credentials.reset"));
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.newPassword"), {
      target: { value: password },
    });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.confirmPassword"), {
      target: { value: password },
    });
    fireEvent.click(screen.getByText("common.confirm"));

    expect(mocks.reset).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
    expect(screen.getByRole("alert").textContent).toBe(
      "representativesVehicles.representatives.form.passwordInvalid",
    );
  });

  it("reuses the same request id when an unchanged credential reset is retried", async () => {
    mocks.reset.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(undefined);
    render(<RepresentativeCredentialAction representative={representative} allowed />);

    fireEvent.click(screen.getByText("representativesVehicles.representatives.credentials.reset"));
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.newPassword"), {
      target: { value: "newpass88" },
    });
    fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.confirmPassword"), {
      target: { value: "newpass88" },
    });

    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      expect((screen.getByText("common.confirm") as HTMLButtonElement).disabled).toBe(false);
    });

    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(2));

    expect(mocks.reset.mock.calls[0]?.[3]).toBe(requestUuid);
    expect(mocks.reset.mock.calls[1]?.[3]).toBe(requestUuid);
  });

  it("preserves an unresolved reset identity across a page remount without persisting the password", async () => {
    const secondUuid = "33333333-3333-4333-8333-333333333333";
    vi.mocked(crypto.randomUUID).mockReturnValueOnce(requestUuid).mockReturnValue(secondUuid);
    mocks.reset.mockImplementationOnce(async () => {
      expect(Object.values(sessionStorage)).toEqual([requestUuid]);
      expect(Object.values(localStorage).sort()).toEqual(["1", "11"]);
      throw { status: 408, code: "REQUEST_TIMEOUT" };
    }).mockResolvedValueOnce(undefined);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "11");
    const password = "remount88";
    const submit = () => {
      fireEvent.click(screen.getByText("representativesVehicles.representatives.credentials.reset"));
      fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.newPassword"), { target: { value: password } });
      fireEvent.change(screen.getByLabelText("representativesVehicles.representatives.fields.confirmPassword"), { target: { value: password } });
      fireEvent.click(screen.getByText("common.confirm"));
    };
    const first = render(<RepresentativeCredentialAction representative={representative} allowed />);
    submit();
    await waitFor(() => expect(screen.getByText("common.confirm")).not.toBeDisabled());
    first.unmount();
    render(<RepresentativeCredentialAction representative={representative} allowed />);
    fireEvent.click(screen.getByText("representativesVehicles.representatives.credentials.reset"));
    expect(screen.getByLabelText("representativesVehicles.representatives.fields.newPassword")).toHaveValue("");
    expect(screen.getByLabelText("representativesVehicles.representatives.fields.confirmPassword")).toHaveValue("");
    changePassword(password);
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(2));
    expect(mocks.reset.mock.calls[1]?.[3]).toBe(mocks.reset.mock.calls[0]?.[3]);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(password);
    expect(sessionStorage.length).toBe(0);
  });

  it("keeps a conflicting recovered request until the operator explicitly starts a new reset", async () => {
    const nextUuid = "33333333-3333-4333-8333-333333333333";
    vi.mocked(crypto.randomUUID).mockReturnValueOnce(requestUuid).mockReturnValue(nextUuid);
    mocks.reset
      .mockRejectedValueOnce({ status: 408, code: "REQUEST_TIMEOUT" })
      .mockRejectedValueOnce({ status: 409, code: "REPRESENTATIVE_IDEMPOTENCY_CONFLICT" })
      .mockRejectedValueOnce({ status: 409, code: "REPRESENTATIVE_IDEMPOTENCY_CONFLICT" })
      .mockResolvedValueOnce(undefined);
    const first = render(<RepresentativeCredentialAction representative={representative} allowed />);
    enterPassword("original88");
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(1);
    first.unmount();

    render(<RepresentativeCredentialAction representative={representative} allowed />);
    enterPassword("different88");
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(2);
    expect(mocks.reset.mock.calls[1]?.[3]).toBe(requestUuid);
    expect(screen.getByRole("alert")).toHaveTextContent("credentials.recoveryConflict");
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);

    changePassword("editedAgain88");
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(3);
    expect(mocks.reset.mock.calls[2]?.[3]).toBe(requestUuid);
    fireEvent.click(screen.getByText("representativesVehicles.representatives.credentials.startNew"));
    expect(mocks.reset).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(4));
    expect(mocks.reset.mock.calls[3]?.[3]).toBe(nextUuid);
    expect(sessionStorage.length).toBe(0);
  });

  it.each([{ status: 503 }, { status: 422, code: "UNKNOWN_OUTCOME" }])("retains opaque recovery for an uncertain response %j and modal closure", async (failure) => {
    mocks.reset.mockRejectedValueOnce(failure).mockResolvedValueOnce(undefined);
    render(<RepresentativeCredentialAction representative={representative} allowed />);
    enterPassword("newpass88");
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(1);
    fireEvent.click(screen.getByText("common.cancel"));
    enterPassword("newpass88");
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(2));
    expect(mocks.reset.mock.calls[1]?.[3]).toBe(requestUuid);
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(sessionStorage.length).toBe(0);
  });

  it("clears a first-send validation rejection so a corrected command gets a new identity", async () => {
    const nextUuid = "33333333-3333-4333-8333-333333333333";
    vi.mocked(crypto.randomUUID).mockReturnValueOnce(requestUuid).mockReturnValue(nextUuid);
    mocks.reset.mockRejectedValueOnce({ status: 422, code: "VALIDATION_ERROR" }).mockResolvedValueOnce(undefined);
    render(<RepresentativeCredentialAction representative={representative} allowed />);
    enterPassword("newpass88");
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(1);
    expect(sessionStorage.length).toBe(0);
    changePassword("corrected88");
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(2));
    expect(mocks.reset.mock.calls[1]?.[3]).toBe(nextUuid);
  });

  it("does not discard an earlier unknown result when a recovered submission fails validation", async () => {
    mocks.reset
      .mockRejectedValueOnce({ status: 408, code: "REQUEST_TIMEOUT" })
      .mockRejectedValueOnce({ status: 422, code: "VALIDATION_ERROR" })
      .mockResolvedValueOnce(undefined);
    render(<RepresentativeCredentialAction representative={representative} allowed />);
    enterPassword("newpass88");
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(1);
    fireEvent.click(screen.getByText("common.confirm"));
    await readyAfterCalls(2);
    expect(sessionStorage.length).toBe(1);
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledTimes(3));
    expect(mocks.reset.mock.calls.map((call) => call[3])).toEqual([requestUuid, requestUuid, requestUuid]);
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(sessionStorage.length).toBe(0);
  });

  it("does not send a reset if opaque recovery cannot be stored", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    render(<RepresentativeCredentialAction representative={representative} allowed />);
    enterPassword("newpass88");
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith(
      "representativesVehicles.representatives.credentials.recoveryUnavailable",
    ));
    expect(mocks.reset).not.toHaveBeenCalled();
  });
});
