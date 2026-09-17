import { describe, expect, it } from "vitest";

import {
  apiErrorMessage,
  normalizeApiErrorResponse,
} from "./apiErrors";

describe("normalizeApiErrorResponse", () => {
  it("prefers the canonical error envelope", () => {
    expect(
      normalizeApiErrorResponse({
        message: "legacy",
        error: {
          code: "PRODUCT_LOCATION_REQUIRED",
          message: "canonical reason",
          context: { location_id: 119 },
          request_id: "req-1",
        },
      })
    ).toEqual({
      code: "PRODUCT_LOCATION_REQUIRED",
      message: "canonical reason",
      context: { location_id: 119 },
      requestId: "req-1",
    });
  });

  it("supports the current backend legacy message object", () => {
    expect(
      normalizeApiErrorResponse({
        message: {
          code: "PRODUCT_LOCATION_REQUIRED",
          message: "legacy reason",
          context: {
            missing_product_variant_ids: [118],
          },
        },
      })
    ).toEqual({
      code: "PRODUCT_LOCATION_REQUIRED",
      message: "legacy reason",
      context: {
        missing_product_variant_ids: [118],
      },
      requestId: undefined,
    });
  });

  it("supports FastAPI detail objects", () => {
    expect(
      normalizeApiErrorResponse({
        detail: {
          code: "SOME_CODE",
          message: "detail reason",
          context: { a: 1 },
        },
      })
    ).toEqual({
      code: "SOME_CODE",
      message: "detail reason",
      context: { a: 1 },
      requestId: undefined,
    });
  });

  it("keeps a legacy string reason", () => {
    expect(
      normalizeApiErrorResponse({
        message: "specific safe reason",
      })
    ).toEqual({
      message: "specific safe reason",
    });
  });
});

describe("apiErrorMessage", () => {
  it("uses the localized known business code", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 409,
        code: "PRODUCT_LOCATION_REQUIRED",
        serverMessage:
          "Every product must be assigned to the warehouse.",
        requestId: "req-2",
      }
    );

    expect(apiErrorMessage(error, "fallback"))
      .toContain("غير مربوط بالمستودع");
  });

  it("does not expose raw unexpected 5xx internals", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 500,
        code: "UNTRANSLATED_500",
        serverMessage:
          "database password and stack trace",
        requestId: "req-secret-test",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "req-secret-test"
    );
    expect(shown).not.toContain(
      "database password"
    );
  });

  it("keeps the request reference for a translated 5xx code", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 500,
        code: "INTERNAL_SERVER_ERROR",
        serverMessage:
          "database password and stack trace",
        requestId: "req-translated-500",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "req-translated-500"
    );
    expect(shown).not.toContain(
      "database password"
    );
  });

  it("uses the localized safe 5xx message even without a request reference", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 503,
        code: "INTERNAL_SERVER_ERROR",
        serverMessage: "internal implementation detail",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "خطأ غير متوقع"
    );
    expect(shown).not.toContain(
      "internal implementation detail"
    );
  });

  it("keeps an unknown deterministic 4xx reason and diagnostics", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 409,
        code: "NEW_BUSINESS_RULE",
        serverMessage:
          "Specific safe business reason.",
        requestId: "req-3",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "Specific safe business reason."
    );
    expect(shown).toContain(
      "NEW_BUSINESS_RULE"
    );
    expect(shown).toContain("req-3");
  });
});
