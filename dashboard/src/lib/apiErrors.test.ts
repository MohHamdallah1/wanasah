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

  it("normalizes FastAPI validation arrays to a stable code", () => {
    expect(
      normalizeApiErrorResponse({
        detail: [
          {
            type: "missing",
            loc: ["body", "name"],
            msg: "Field required",
          },
        ],
      })
    ).toEqual({
      code: "VALIDATION_ERROR",
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

  it("shows a translated safe 503 service error with its reference", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 503,
        code: "LIVE_STOCK_PROJECTION_NOT_READY",
        serverMessage:
          "internal projection implementation detail",
        requestId: "req-live-stock-503",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "الرصيد الحي قيد التحديث"
    );
    expect(shown).toContain(
      "req-live-stock-503"
    );
    expect(shown).not.toContain(
      "internal projection implementation detail"
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

  it("keeps unknown coded 4xx diagnostics language-neutral", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 409,
        code: "NEW_BUSINESS_RULE",
        serverMessage:
          "Specific server-language business reason.",
        requestId: "req-3",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain("fallback");
    expect(shown).toContain(
      "NEW_BUSINESS_RULE"
    );
    expect(shown).toContain("req-3");
    expect(shown).not.toContain(
      "Specific server-language business reason."
    );
  });

  it("treats a code-like local Error message as a stable code", () => {
    const shown = apiErrorMessage(
      new Error("LOCAL_PRODUCT_CONTRACT_INVALID"),
      "localized fallback"
    );

    expect(shown).toContain(
      "localized fallback"
    );
    expect(shown).toContain(
      "LOCAL_PRODUCT_CONTRACT_INVALID"
    );
  });
});
