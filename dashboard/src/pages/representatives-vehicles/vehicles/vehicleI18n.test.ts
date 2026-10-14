import { describe, expect, it } from "vitest";

import { representativesVehicles } from "@/i18n/representativesVehicles";

const flatten = (value: unknown): string[] => {
  if (typeof value === "string") return [value];
  if (!value || typeof value !== "object") return [];
  return Object.values(value).flatMap(flatten);
};

describe("Vehicle bilingual copy", () => {
  it("keeps Arabic Vehicle copy intact instead of replacement question marks", () => {
    const values = flatten(representativesVehicles.ar.vehicles);
    expect(values.length).toBeGreaterThan(20);
    expect(values.some((value) => /[\u0600-\u06FF]/.test(value))).toBe(true);
    expect(values.some((value) => /\?{3,}/.test(value))).toBe(false);
  });

  it("keeps the shared no-access state localized for Arabic Vehicle access", () => {
    expect(representativesVehicles.ar.noAccess).toMatch(/[\u0600-\u06FF]/);
  });

  it("keeps English action and lifecycle punctuation readable", () => {
    expect(representativesVehicles.en.vehicles.actionsMenu).toContain("—");
    expect(representativesVehicles.en.vehicles.lifecycle.deactivateConfirm).toContain("“{{plate}}”");
    expect(representativesVehicles.en.vehicles.lifecycle.reactivateConfirm).toContain("“{{plate}}”");
  });
});
