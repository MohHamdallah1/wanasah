import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import i18n from "@/i18n";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
} from "@/lib/durableOperations";

describe("durable command P3 guarantees", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await i18n.changeLanguage("en");
  });

  it("retains unresolved payload-bearing commands beyond seven days", async () => {
    const start = 1_000_000;
    vi.spyOn(Date, "now").mockReturnValue(start);

    const scope = durableScope(
      1,
      2,
      "catalog-barcode-create-v2",
      10,
    );
    const payload = {
      uom_id: 1,
      barcode: "ABC123",
      barcode_type: "INTERNAL",
      is_primary: false,
      valid_from: null,
      valid_to: null,
    };

    const created =
      await getOrCreateDurableCommand(
        scope,
        payload,
      );

    vi.spyOn(Date, "now").mockReturnValue(
      start +
        8 * 24 * 60 * 60 * 1000,
    );

    const restored =
      await readDurableCommand<
        typeof payload
      >(scope);

    expect(restored).toEqual(created);
    expect(
      localStorage.getItem(scope),
    ).not.toBeNull();
  });

  it("fails closed when a stored command payload no longer matches its hash", async () => {
    const scope = durableScope(
      1,
      2,
      "catalog-barcode-create-v2",
      10,
    );
    const payload = {
      uom_id: 1,
      barcode: "ORIGINAL",
      barcode_type: "INTERNAL",
      is_primary: false,
      valid_from: null,
      valid_to: null,
    };

    await getOrCreateDurableCommand(
      scope,
      payload,
    );

    const raw = localStorage.getItem(
      scope,
    );
    expect(raw).not.toBeNull();

    const stored = JSON.parse(
      String(raw),
    ) as {
      payload: {
        barcode: string;
      };
    };
    stored.payload.barcode =
      "TAMPERED";
    localStorage.setItem(
      scope,
      JSON.stringify(stored),
    );

    await expect(
      readDurableCommand(scope),
    ).rejects.toMatchObject({
      code: "DURABLE_OPERATION_CORRUPT",
    });

    expect(
      localStorage.getItem(scope),
    ).not.toBeNull();
  });

  it("presents a pending-command conflict through Arabic translation", async () => {
    await i18n.changeLanguage("ar");

    const scope = durableScope(
      1,
      2,
      "catalog-barcode-create-v2",
      10,
    );

    await getOrCreateDurableCommand(
      scope,
      {
        barcode: "FIRST",
      },
    );

    let conflict: unknown;
    try {
      await getOrCreateDurableCommand(
        scope,
        {
          barcode: "SECOND",
        },
      );
    } catch (error) {
      conflict = error;
    }

    expect(conflict).toMatchObject({
      code: "DURABLE_OPERATION_PENDING",
    });
    expect(
      apiErrorMessage(
        conflict,
        "fallback",
      ),
    ).toBe(
      "يوجد طلب سابق لنفس العملية لم تُحسم نتيجته بعد. أعد نفس الطلب أو أكمل تسويته قبل إرسال طلب مختلف.",
    );
  });
});
