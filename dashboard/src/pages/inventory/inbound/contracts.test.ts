import { describe, expect, it } from "vitest";

import type { CatalogVariant } from "@/features/catalog/contracts";
import {
  buildInboundItems,
  emptyInboundBatch,
  InboundRowValidationError,
  parseInboundDrafts,
  type InboundDraftMap,
  type InboundVariantOptions,
} from "./contracts";

const options = new Map<number, InboundVariantOptions>([
  [
    7,
    {
      product_variant_id: 7,
      base_uom_id: 1,
      uoms: [
        { id: 1, code: "EACH", name: "Each", factor_to_base: "1" },
        { id: 2, code: "BOX", name: "Box", factor_to_base: "10" },
      ],
    },
  ],
]);

const variant = (
  lot: CatalogVariant["lot_control_mode"],
  expiry: CatalogVariant["expiry_control_mode"],
): CatalogVariant => ({
  id: 7,
  product_id: 3,
  sku: "SKU-7",
  gtin: null,
  name: "Product",
  base_uom: { id: 1, code: "EACH", name: "Each" },
  quantity_scale: 3,
  quantity_step: "0.125",
  lot_control_mode: lot,
  expiry_control_mode: expiry,
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  lifecycle_revision: 1,
  version: 1,
  published_at: "2026-10-01T00:00:00Z",
  retired_at: null,
  archived_at: null,
});

const drafts = (
  patch: Partial<ReturnType<typeof emptyInboundBatch>> = {},
): InboundDraftMap => ({
  "7": [
    {
      ...emptyInboundBatch("row-1", "1"),
      quantity: "1.125",
      unit_cost: "2.500000",
      ...patch,
    },
  ],
});

const build = (
  lot: CatalogVariant["lot_control_mode"],
  expiry: CatalogVariant["expiry_control_mode"],
  patch: Partial<ReturnType<typeof emptyInboundBatch>> = {},
  asOfDate?: string,
) =>
  buildInboundItems(
    drafts(patch),
    new Map([["7", variant(lot, expiry)]]),
    options,
    asOfDate,
  );

const expectRowError = (
  run: () => unknown,
  code: string,
  field: string,
  rowId = "row-1",
) => {
  try {
    run();
    throw new Error("Expected validation error");
  } catch (error) {
    expect(error).toBeInstanceOf(InboundRowValidationError);
    expect(error).toMatchObject({ code, field, row_id: rowId });
  }
};

describe("Inbound draft recovery", () => {
  it("restores an unfinished draft with an empty quantity without discarding other products", () => {
    const saved = {
      "7": [{ ...emptyInboundBatch("row-7", "1"), quantity: "", unit_cost: "3.75" }],
      "8": [{ ...emptyInboundBatch("row-8", "2"), quantity: "2", unit_cost: "5" }],
    };
    expect(parseInboundDrafts(JSON.stringify(saved))).toEqual(saved);
  });

  it("preserves incomplete edits and skips only malformed rows", () => {
    const saved = {
      "7": [
        { ...emptyInboundBatch("row-7", "1"), quantity: "1.", unit_cost: "2.", expiry_date: "2026-0" },
        { row_id: "broken", quantity: 123 },
      ],
      "8": [{ ...emptyInboundBatch("row-8", "1"), quantity: "4", unit_cost: "6" }],
    };
    expect(parseInboundDrafts(JSON.stringify(saved))).toEqual({
      "7": [saved["7"][0]],
      "8": saved["8"],
    });
    expect(parseInboundDrafts("{broken")).toEqual({});
  });
});

describe("Checkpoint 1 inbound tracking contract", () => {
  it("keeps lot identity product-specific and never invents one", () => {
    expect(
      build("REQUIRED", "OPTIONAL", { batch_number: "LOT-7" })[0],
    ).toMatchObject({ batch_number: "LOT-7" });
    expect(build("OPTIONAL", "OPTIONAL")[0]).toMatchObject({
      batch_number: null,
    });
    expect(
      build("NONE", "OPTIONAL", { batch_number: "STALE-LOT" })[0],
    ).toMatchObject({ batch_number: null });
  });

  it("requires a lot only for REQUIRED mode", () => {
    expectRowError(
      () => build("REQUIRED", "OPTIONAL"),
      "INBOUND_LOT_REQUIRED",
      "batch_number",
    );
    expect(build("OPTIONAL", "OPTIONAL")[0].batch_number).toBeNull();
    expect(build("NONE", "OPTIONAL")[0].batch_number).toBeNull();
  });

  it("implements REQUIRED / OPTIONAL / NONE expiry semantics", () => {
    expectRowError(
      () => build("OPTIONAL", "REQUIRED"),
      "INBOUND_EXPIRY_REQUIRED",
      "expiry_date",
    );
    expect(build("OPTIONAL", "OPTIONAL")[0].expiry_date).toBeNull();
    expect(
      build("OPTIONAL", "NONE", { expiry_date: "2030-01-01" })[0]
        .expiry_date,
    ).toBeNull();
  });

  it("keeps production optional when any tracking field is active", () => {
    expect(
      build("OPTIONAL", "NONE", { production_date: "2026-10-01" })[0]
        .production_date,
    ).toBe("2026-10-01");
    expect(
      build("NONE", "OPTIONAL", { production_date: "2026-10-01" })[0]
        .production_date,
    ).toBe("2026-10-01");
  });

  it("drops all hidden stale tracking values when both modes are NONE", () => {
    expect(
      build(
        "NONE",
        "NONE",
        {
          batch_number: "STALE-LOT",
          production_date: "2026-10-01",
          expiry_date: "2030-01-01",
        },
      )[0],
    ).toMatchObject({
      batch_number: null,
      production_date: null,
      expiry_date: null,
    });
  });

  it("keeps duplicate and metadata validation scoped to real lots", () => {
    const duplicateReal: InboundDraftMap = {
      "7": [
        {
          ...emptyInboundBatch("row-1", "1"),
          quantity: "1",
          unit_cost: "2",
          batch_number: "LOT-1",
        },
        {
          ...emptyInboundBatch("row-2", "1"),
          quantity: "1",
          unit_cost: "2",
          batch_number: "LOT-1",
        },
      ],
    };
    expectRowError(
      () =>
        buildInboundItems(
          duplicateReal,
          new Map([["7", variant("OPTIONAL", "OPTIONAL")]]),
          options,
        ),
      "INBOUND_DUPLICATE_BATCH_UOM_LINE",
      "uom_id",
      "row-2",
    );

    const anonymous = structuredClone(duplicateReal);
    anonymous["7"].forEach((row) => {
      row.batch_number = "";
    });
    expect(
      buildInboundItems(
        anonymous,
        new Map([["7", variant("OPTIONAL", "OPTIONAL")]]),
        options,
      ),
    ).toHaveLength(2);
  });

  it("reports the exact metadata field for a real-lot conflict", () => {
    const conflict: InboundDraftMap = {
      "7": [
        {
          ...emptyInboundBatch("row-1", "1"),
          quantity: "1",
          unit_cost: "2",
          batch_number: "LOT-1",
          expiry_date: "2030-01-01",
        },
        {
          ...emptyInboundBatch("row-2", "2"),
          quantity: "1",
          unit_cost: "2",
          batch_number: "LOT-1",
          expiry_date: "2031-01-01",
        },
      ],
    };
    expectRowError(
      () =>
        buildInboundItems(
          conflict,
          new Map([["7", variant("REQUIRED", "OPTIONAL")]]),
          options,
        ),
      "INBOUND_BATCH_METADATA_CONFLICT",
      "expiry_date",
      "row-2",
    );
  });

  it("rejects expired stock and future production against the company local date", () => {
    expectRowError(
      () => build(
        "REQUIRED",
        "REQUIRED",
        {
          batch_number: "LOT-PAST",
          production_date: "2026-10-01",
          expiry_date: "2026-10-21",
        },
        "2026-10-22",
      ),
      "INBOUND_BATCH_EXPIRED",
      "expiry_date",
    );
    expectRowError(
      () => build(
        "REQUIRED",
        "REQUIRED",
        {
          batch_number: "LOT-FUTURE",
          production_date: "2026-10-23",
          expiry_date: "2026-12-01",
        },
        "2026-10-22",
      ),
      "INBOUND_PRODUCTION_DATE_FUTURE",
      "production_date",
    );
    expect(
      build(
        "REQUIRED",
        "REQUIRED",
        {
          batch_number: "LOT-TODAY",
          production_date: "2026-10-22",
          expiry_date: "2026-10-22",
        },
        "2026-10-22",
      )[0],
    ).toMatchObject({
      production_date: "2026-10-22",
      expiry_date: "2026-10-22",
    });
  });

  it("preserves exact quantity, UOM and money validation with row identity", () => {
    expectRowError(
      () => build("OPTIONAL", "OPTIONAL", { quantity: "1.001" }),
      "INBOUND_QUANTITY_CONVERSION_INVALID",
      "quantity",
    );
    expectRowError(
      () => build("OPTIONAL", "OPTIONAL", { uom_id: "999" }),
      "INBOUND_UOM_REQUIRED",
      "uom_id",
    );
    expectRowError(
      () => build("OPTIONAL", "OPTIONAL", { unit_cost: "1.1234567" }),
      "INBOUND_UNIT_COST_INVALID",
      "unit_cost",
    );
  });
});