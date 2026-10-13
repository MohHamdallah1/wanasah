import { describe, expect, it } from "vitest";

import {
  RepresentativeContractError,
  normalizeOptionalPhone,
  parseRepresentative,
  parseRepresentativeList,
  parseRepresentativeResponse,
} from "./contracts";

const representative = {
  id: 17,
  username: "rep17",
  name: "Ahmad Saleh",
  phone: "+962790000000",
  is_active: true,
  created_at: "2026-10-13T10:00:00Z",
  updated_at: null,
};

describe("representative contracts", () => {
  it("parses a direct representative without exposing unknown transport fields", () => {
    expect(parseRepresentative({ ...representative, company_id: 9, company_principal_id: 77 })).toEqual(representative);
  });

  it("isolates supported list envelope variants", () => {
    expect(parseRepresentativeList([representative]).items).toHaveLength(1);
    expect(parseRepresentativeList({ items: [representative] }).items[0]?.username).toBe("rep17");
  });

  it("isolates supported mutation wrapper variants", () => {
    expect(parseRepresentativeResponse({ representative }).id).toBe(17);
    expect(parseRepresentativeResponse(representative).id).toBe(17);
  });

  it("fails closed on malformed representative data", () => {
    expect(() => parseRepresentative({ ...representative, id: "17" })).toThrow(RepresentativeContractError);
    expect(() => parseRepresentativeList({ data: [representative] })).toThrow(RepresentativeContractError);
  });

  it("normalizes optional phone without inventing values", () => {
    expect(normalizeOptionalPhone("  +962790000000  ")).toBe("+962790000000");
    expect(normalizeOptionalPhone("   ")).toBeNull();
  });
});
