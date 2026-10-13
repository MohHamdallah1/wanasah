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

beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => requestUuid) });
  mocks.reset.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
});
