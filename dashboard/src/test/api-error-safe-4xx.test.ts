import { describe, expect, it } from "vitest";

import { apiErrorMessage } from "@/lib/apiErrors";

describe("API error safe deterministic 4xx messaging", () => {
  it("shows an untranslated safe 4xx server reason instead of a generic fallback", () => {
    const error = Object.assign(new Error("HTTP 409"), {
      status: 409,
      code: "WHOLE_PRODUCT_QUALITY_CONFLICT",
      serverMessage: "Safe inventory conflict reason from the server.",
      requestId: "trace-409",
    });

    const message = apiErrorMessage(error, "Generic fallback.");
    expect(message).toContain("Safe inventory conflict reason from the server.");
    expect(message).not.toContain("trace-409");
    expect(message).not.toContain("WHOLE_PRODUCT_QUALITY_CONFLICT");
  });

  it("does not expose request IDs or raw codes for a 4xx fallback", () => {
    const error = Object.assign(new Error("HTTP 409"), {
      status: 409,
      code: "UNKNOWN_BUSINESS_CONFLICT",
      requestId: "trace-409-fallback",
    });

    const message = apiErrorMessage(error, "تعذر تنفيذ العملية الآن.");
    expect(message).toBe("تعذر تنفيذ العملية الآن.");
    expect(message).not.toContain("trace-409-fallback");
    expect(message).not.toContain("UNKNOWN_BUSINESS_CONFLICT");
  });

  it("still redacts an unknown 5xx server reason", () => {
    const error = Object.assign(new Error("HTTP 500"), {
      status: 500,
      code: "UNKNOWN_DATABASE_FAILURE",
      serverMessage: "secret database internals",
      requestId: "trace-500",
    });

    const message = apiErrorMessage(error, "Generic fallback.");
    expect(message).not.toContain("secret database internals");
    expect(message).toContain("trace-500");
  });
});
