import { describe, expect, it } from "vitest";

import {
  RepresentativeContractError,
  normalizeDebtLimit,
  normalizeOptionalPhone,
  parseRepresentative,
  parseRepresentativeList,
} from "./contracts";

const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: "+962790000000",
  is_active: true,
  can_allow_debt: true,
  max_debt_limit: "125.500",
};

describe("representative frozen wire contract", () => {
  it("parses only the frozen representative view", () => {
    expect(parseRepresentative({ ...representative, principal_id: 99, company_id: 3 })).toEqual(representative);
  });

  it("requires the frozen cursor envelope", () => {
    expect(parseRepresentativeList({ items: [representative], next_cursor: "opaque", has_more: true })).toEqual({
      items: [representative],
      next_cursor: "opaque",
      has_more: true,
    });
    expect(() => parseRepresentativeList([representative])).toThrow(RepresentativeContractError);
    expect(() => parseRepresentativeList({ items: [representative] })).toThrow(RepresentativeContractError);
  });

  it("fails closed on binary-float debt values and malformed rows", () => {
    expect(() => parseRepresentative({ ...representative, max_debt_limit: 125.5 })).toThrow(RepresentativeContractError);
    expect(() => parseRepresentative({ ...representative, id: "17" })).toThrow(RepresentativeContractError);
  });

  it("normalizes exact decimal input without float arithmetic", () => {
    expect(normalizeDebtLimit("125.5")).toBe("125.500");
    expect(normalizeDebtLimit("0")).toBe("0.000");
    expect(normalizeDebtLimit("999999999.999")).toBe("999999999.999");
    expect(normalizeDebtLimit("1000000000.000")).toBeNull();
    expect(normalizeDebtLimit("1.2345")).toBeNull();
  });

  it("normalizes optional phone without inventing values", () => {
    expect(normalizeOptionalPhone("  +962790000000  ")).toBe("+962790000000");
    expect(normalizeOptionalPhone("   ")).toBeNull();
  });
});
