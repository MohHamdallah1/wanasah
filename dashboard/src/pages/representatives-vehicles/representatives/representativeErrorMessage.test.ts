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
  it("owns stable Wave 1 business copy instead of exposing backend English", () => {
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
  });

  it("keeps the shared safe fallback for unknown codes", () => {
    expect(representativeErrorMessage({ code: "UNKNOWN" }, "fallback")).toBe("fallback");
  });
});
