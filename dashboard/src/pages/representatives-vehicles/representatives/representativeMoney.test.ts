import { describe, expect, it } from "vitest";

import { formatRepresentativeMoney } from "./representativeMoney";

describe("formatRepresentativeMoney", () => {
  it.each([
    ["50.000", "50 د.أ"],
    ["50.500", "50.5 د.أ"],
    ["50.050", "50.05 د.أ"],
    ["50.005", "50.005 د.أ"],
    ["1250.000", "1,250 د.أ"],
    ["1250.750", "1,250.75 د.أ"],
  ])("formats %s without binary floating point", (raw, expected) => {
    expect(formatRepresentativeMoney(raw, { currencyLabel: "د.أ" })).toBe(expected);
  });

  it("uses the English JOD label without changing exact decimal digits", () => {
    expect(formatRepresentativeMoney("1250.005", { currencyLabel: "JOD" })).toBe("1,250.005 JOD");
  });

  it("can produce an ungrouped human-friendly edit value", () => {
    expect(formatRepresentativeMoney("50.000", { groupThousands: false })).toBe("50");
    expect(formatRepresentativeMoney("50.500", { groupThousands: false })).toBe("50.5");
    expect(formatRepresentativeMoney("50.005", { groupThousands: false })).toBe("50.005");
    expect(formatRepresentativeMoney("1250.000", { groupThousands: false })).toBe("1250");
  });
});
