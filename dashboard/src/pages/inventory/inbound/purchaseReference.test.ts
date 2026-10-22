import { describe, expect, it } from "vitest";
import {
  conciseMoney, inboundReferenceChoices, parseInboundOptions, prefilledInboundRow,
  type InboundItemPayload,
} from "./contracts";

const defaultPayload = (id: number, unitCost: string, uomId: number): InboundItemPayload => ({
  product_variant_id: id,
  quantity: "2",
  uom_id: uomId,
  unit_cost: unitCost,
  batch_number: null,
  production_date: null,
  expiry_date: null,
});

const withOption = (reference: unknown) => ({
  currency_code: "JOD",
  items: [{
    product_variant_id: 7,
    base_uom_id: 1,
    uoms: [
      { id: 1, code: "EACH", name: "Each", factor_to_base: "1" },
      { id: 2, code: "CARTON", name: "Carton", factor_to_base: "20" },
    ],
    purchase_cost_reference: reference,
  }],
});

describe("Inbound purchase cost reference V1", () => {
  it("prefills only a new untouched row in the stored native UOM", () => {
    const option = parseInboundOptions(withOption({
      amount: "8.500000", purchase_uom_id: 2, currency_code: "JOD", revision: 3,
    })).items[0];
    const row = prefilledInboundRow("r1", "1", option);
    expect(row.unit_cost).toBe("8.5");
    expect(row.uom_id).toBe("2");
    // Latest local draft UX represents untouched quantity as a blank input.
    expect(row.quantity).toBe("");
  });

  it("renders reference money concisely without changing exact decimal meaning", () => {
    expect(conciseMoney("7.000000")).toBe("7");
    expect(conciseMoney("7.500000")).toBe("7.5");
    expect(conciseMoney("7.050000")).toBe("7.05");
  });

  it("leaves a missing or unauthorized suggestion unknown, not 0", () => {
    const option = parseInboundOptions(withOption(null)).items[0];
    expect(option.purchase_cost_reference).toBeNull();
    expect(prefilledInboundRow("r1", "1", option)).toMatchObject({
      unit_cost: "", uom_id: "1",
    });
  });

  it("rejects mismatched currency, precision and unavailable UOM from suggestions", () => {
    for (const bad of [
      { amount: "8.5", purchase_uom_id: 2, currency_code: "USD", revision: 2 },
      { amount: "8.1234567", purchase_uom_id: 2, currency_code: "JOD", revision: 2 },
      { amount: "8.5", purchase_uom_id: 999, currency_code: "JOD", revision: 2 },
    ]) {
      expect(() => parseInboundOptions(withOption(bad))).toThrow();
    }
  });

  it("does not invent a selection for one actual cost pair", () => {
    expect(inboundReferenceChoices([
      defaultPayload(7, "8.5", 2), defaultPayload(7, "8.500000", 2),
    ]).size).toBe(0);
  });

  it("requires an explicit native pair for mixed costs and retains other products separately", () => {
    const choices = inboundReferenceChoices([
      defaultPayload(7, "4", 2),
      defaultPayload(8, "3", 1),
      defaultPayload(7, "4.250000", 2),
      defaultPayload(7, "1", 1),
    ]);
    expect([...choices.keys()]).toEqual([7]);
    expect(choices.get(7)).toEqual([
      { product_variant_id: 7, uom_id: 1, unit_cost: "1.000000" },
      { product_variant_id: 7, uom_id: 2, unit_cost: "4.000000" },
      { product_variant_id: 7, uom_id: 2, unit_cost: "4.250000" },
    ]);
  });

  it("is order-independent and never averages distinct actual receipt costs", () => {
    const items = [
      defaultPayload(7, "5", 1),
      defaultPayload(7, "7", 1),
    ];
    expect(inboundReferenceChoices([...items].reverse())).toEqual(inboundReferenceChoices(items));
  });
});
