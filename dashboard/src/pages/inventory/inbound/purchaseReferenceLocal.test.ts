import { describe, expect, it } from "vitest";
import {
  inboundReferenceChoices, parseInboundOptions, prefilledInboundRow,
  type InboundItemPayload,
} from "./contracts";

const options = (ref: unknown) => ({
  currency_code: "JOD",
  as_of_date: "2026-10-22",
  items: [{ product_variant_id: 7, base_uom_id: 1,
    uoms: [
      { id: 1, code: "EACH", name: "Each", factor_to_base: "1" },
      { id: 2, code: "CARTON", name: "Carton", factor_to_base: "24" },
    ],
    purchase_cost_reference: ref,
  }],
});
const line = (cost: string, uom = 2): InboundItemPayload => ({
  product_variant_id: 7,
  quantity: "2",
  uom_id: uom,
  unit_cost: cost,
  batch_number: null,
  production_date: null,
  expiry_date: null,
});
describe("Local Inventory Inbound purchase-reference reconciliation", () => {
  it("restores a suggestion only for a brand new row in its actual purchase unit", () => {
    const result = parseInboundOptions(options({
      amount: "4.250000", purchase_uom_id: 2,
      currency_code: "JOD", revision: 3,
    }));
    expect(prefilledInboundRow("r", "1", result.items[0])).toMatchObject({
      unit_cost: "4.25", uom_id: "2", quantity: "",
    });
  });
  it("does not manufacture cost for absent/unauthorized reference", () => {
    const item = parseInboundOptions(options(null)).items[0];
    expect(prefilledInboundRow("r", "1", item)).toMatchObject({unit_cost:"",uom_id:"1"});
  });
  it("fails closed for unsupported currency, UOM and excessive precision", () => {
    for(const ref of [
      {amount:"4.2",purchase_uom_id:2,currency_code:"USD",revision:3},
      {amount:"4.1234567",purchase_uom_id:2,currency_code:"JOD",revision:3},
      {amount:"4.2",purchase_uom_id:999,currency_code:"JOD",revision:3},
    ]) expect(() => parseInboundOptions(options(ref))).toThrow();
  });
  it("requires explicit source native cost choice, never a computed average", () => {
    expect(inboundReferenceChoices([line("3.000000"),line("4.000000")]).get(7))
      .toEqual([
        {product_variant_id:7,uom_id:2,unit_cost:"3.000000"},
        {product_variant_id:7,uom_id:2,unit_cost:"4.000000"},
      ]);
    expect(inboundReferenceChoices([line("3"),line("3.000000")]).size).toBe(0);
    expect(inboundReferenceChoices([line("3"),line("3",1)]).get(7)?.length).toBe(2);
  });
  it("uses exact decimal strings and independent of receipt line ordering", () => {
    const a=[line("6"),line("4.25",1),line("8.5")];
    expect(inboundReferenceChoices(a)).toEqual(inboundReferenceChoices([...a].reverse()));
  });
});