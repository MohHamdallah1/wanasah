import { describe, expect, it } from "vitest";
import {
  assertReferenceSaved, parsePurchaseReference, validateReferenceCommand,
} from "../pages/products/purchaseReference/contracts";

const validReference = {
  product_variant_id: 18,
  amount: "4.500000",
  purchase_uom_id: 3,
  purchase_uom_code: "CARTON",
  base_uom_id: 2,
  base_uom_code: "EACH",
  currency_code: "JOD",
  revision: 2,
  source: "MANUAL_PRODUCT",
};

describe("Purchase cost reference transport", () => {
  it("keeps missing reference unknown rather than defaulting purchase cost to zero", () => {
    expect(parsePurchaseReference({ reference: null })).toBeNull();
  });
  it("reads the explicit purchase unit, company currency and independent revision", () => {
    expect(parsePurchaseReference({ reference: validReference })).toMatchObject(validReference);
  });
  it("fails closed on malformed, missing or imprecise server values", () => {
    for (const reference of [
      { ...validReference, amount: 2.5 },
      { ...validReference, amount: "1.1234567" },
      { ...validReference, revision: 0 },
      { ...validReference, purchase_uom_id: -1 },
      { ...validReference, currency_code: "" },
      { ...validReference, source: "PRICING" },
    ]) {
      expect(() => parsePurchaseReference({ reference })).toThrow();
    }
    expect(() => parsePurchaseReference({})).toThrow();
  });
  it("sends money as a decimal string with no float calculation", () => {
    expect(validateReferenceCommand({
      amount: "4.250000", purchase_uom_id: 3, currency_code: "JOD",
    }, 2)).toEqual({
      amount: "4.250000", purchase_uom_id: 3, currency_code: "JOD", expected_revision: 2,
    });
  });
  it("only completes durable writes on the exact confirmed amount, UOM, currency, variant, and revision", () => {
    const command = { amount: "4.5", purchase_uom_id: 3, currency_code: "JOD", expected_revision: 2 };
    const saved = { reference: { ...validReference, revision: 3 } };
    expect(() => assertReferenceSaved(saved, command, 18)).not.toThrow();
    for (const mismatch of [
      { ...saved.reference, revision: 4 },
      { ...saved.reference, product_variant_id: 19 },
      { ...saved.reference, amount: "4.250000" },
      { ...saved.reference, purchase_uom_id: 2 },
      { ...saved.reference, currency_code: "USD" },
    ]) {
      expect(() => assertReferenceSaved({ reference: mismatch }, command, 18)).toThrow();
    }
    expect(() => assertReferenceSaved({ message: "OK" }, command, 18)).toThrow();
  });

  it("rejects invalid precision, scale, missing UOM, or unsupported currency", () => {
    for (const amount of ["-1", "3.1234567", "Infinity", "1e2", ""]) {
      expect(() => validateReferenceCommand({
        amount, purchase_uom_id: 3, currency_code: "JOD",
      }, 0)).toThrow();
    }
    expect(() => validateReferenceCommand({
      amount: "2", purchase_uom_id: 0, currency_code: "JOD",
    }, 0)).toThrow();
    expect(() => validateReferenceCommand({
      amount: "2", purchase_uom_id: 1, currency_code: "JOD",
    }, -1)).toThrow();
  });
});