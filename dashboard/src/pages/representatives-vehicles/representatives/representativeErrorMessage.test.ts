import { describe, expect, it, vi } from "vitest";

vi.mock("@/i18n", () => ({
  default: { t: (key: string) => key },
}));
vi.mock("@/lib/apiErrors", () => ({
  apiErrorCode: (error: { code?: string }) => error.code,
  apiErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

import { representativeErrorMessage } from "./representativeErrorMessage";

describe("representativeErrorMessage", () => {
  it("owns stable Representative business copy instead of exposing backend English", () => {
    expect(
      representativeErrorMessage(
        { code: "REPRESENTATIVE_USERNAME_CONFLICT" },
        "fallback",
      ),
    ).toBe("representativesVehicles.representatives.errors.usernameConflict");
    expect(
      representativeErrorMessage(
        { code: "REPRESENTATIVE_NOT_FOUND" },
        "fallback",
      ),
    ).toBe("representativesVehicles.representatives.errors.notFound");
    expect(
      representativeErrorMessage(
        { code: "REPRESENTATIVE_DEACTIVATION_BLOCKED" },
        "fallback",
      ),
    ).toBe("representativesVehicles.representatives.errors.deactivationBlocked");
    expect(
      representativeErrorMessage(
        { code: "REPRESENTATIVE_ALREADY_ACTIVE" },
        "fallback",
      ),
    ).toBe("representativesVehicles.representatives.errors.alreadyActive");
    expect(
      representativeErrorMessage(
        { code: "REPRESENTATIVE_SESSION_INVALIDATION_REJECTED" },
        "fallback",
      ),
    ).toBe("representativesVehicles.representatives.errors.sessionInvalidationRejected");
  });

  it("maps canonical credential-policy rejections to the local password copy", () => {
    expect(
      representativeErrorMessage(
        { code: "REPRESENTATIVE_COMPANY_PASSWORD_TOO_LONG" },
        "fallback",
      ),
    ).toBe("representativesVehicles.representatives.form.passwordInvalid");
  });

  it("keeps the shared safe fallback for unknown codes", () => {
    expect(representativeErrorMessage({ code: "UNKNOWN" }, "fallback")).toBe("fallback");
  });

  it("localizes catalog paging and unavailable-account errors without exposing internal compatibility terms", () => {
    for (const code of ["REPRESENTATIVE_IDENTITY_INCONSISTENT", "REPRESENTATIVE_OPERATIONAL_COMPATIBILITY_MISSING"]) {
      expect(representativeErrorMessage({ code }, "fallback")).toBe("representativesVehicles.representatives.errors.unavailable");
    }
    expect(representativeErrorMessage({ code: "REPRESENTATIVE_CURSOR_INVALID" }, "fallback")).toBe("representativesVehicles.representatives.errors.cursorInvalid");
  });
});
