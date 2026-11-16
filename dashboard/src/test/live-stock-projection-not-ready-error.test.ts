import { describe, expect, it } from "vitest";
import i18n from "@/i18n";
import { apiErrorMessage } from "@/lib/apiErrors";

describe("Live Stock not-ready service error", () => {
  it("explains the required administrator action without an unexplained tracking UUID in Arabic", async () => {
    await i18n.changeLanguage("ar");
    const message = apiErrorMessage(
      {
        status: 503,
        code: "LIVE_STOCK_PROJECTION_NOT_READY",
        requestId: "5aca082e-aa80-4c33-a31e-a545d15ebe27",
        serverMessage: "الرصيد الحي قيد التحديث. أعد المحاولة بعد لحظات.",
      },
      "تعذر تحديث الرصيد الحي",
    );
    expect(message).toContain("مسؤول النظام");
    expect(message).toContain("إعادة بنائها");
    expect(message).not.toContain("5aca082e");
    expect(message).not.toContain("بعد لحظات");
  });

  it("provides the same actionable failure explanation in English", async () => {
    await i18n.changeLanguage("en");
    const message = apiErrorMessage(
      { status: 503, code: "LIVE_STOCK_PROJECTION_NOT_READY", requestId: "REF-123" },
      "Loading failed",
    );
    expect(message).toContain("administrator");
    expect(message).toContain("rebuild");
    expect(message).not.toContain("REF-123");
  });
});
