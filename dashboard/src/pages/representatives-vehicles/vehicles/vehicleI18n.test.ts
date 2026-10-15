import { describe, expect, it } from "vitest";

import { representativesVehicles } from "@/i18n/representativesVehicles";

const flatten = (value: unknown): string[] => {
  if (typeof value === "string") return [value];
  if (!value || typeof value !== "object") return [];
  return Object.values(value).flatMap(flatten);
};

const keyPaths = (value: unknown, prefix = ""): string[] => {
  if (!value || typeof value !== "object") return prefix ? [prefix] : [];
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === "object" ? keyPaths(child, path) : [path];
  });
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

  it("keeps Arabic and English translation keys in exact parity", () => {
    expect(keyPaths(representativesVehicles.ar).sort()).toEqual(keyPaths(representativesVehicles.en).sort());
  });

  it("localizes oil-target validation in both languages", () => {
    expect(representativesVehicles.ar.vehicles.form.oilMustBeFuture).toMatch(/[\u0600-\u06FF]/);
    expect(representativesVehicles.ar.vehicles.quickActions.oilMustBeFuture).toContain("{{mileage}}");
    expect(representativesVehicles.ar.vehicles.errors.oilChangeTargetInvalid).toMatch(/[\u0600-\u06FF]/);
    expect(representativesVehicles.en.vehicles.quickActions.oilMustBeFuture).toContain("{{mileage}}");
  });

  it("keeps vehicle information copy under the Vehicle namespace", () => {
    expect(representativesVehicles.ar.vehicles.details.action).toMatch(/[\u0600-\u06FF]/);
    expect(representativesVehicles.en.vehicles.details.action).toBe("Vehicle information");
    expect(representativesVehicles.ar.representatives).not.toHaveProperty("details");
  });

  it("keeps English action and lifecycle punctuation readable", () => {
    expect(representativesVehicles.en.vehicles.actionsMenu).toContain("—");
    expect(representativesVehicles.en.vehicles.lifecycle.deactivateConfirm).toContain("“{{plate}}”");
    expect(representativesVehicles.en.vehicles.lifecycle.reactivateConfirm).toContain("“{{plate}}”");
  });

  it("exposes exact Arabic and English Vehicle form badges", () => {
    expect(representativesVehicles.ar.vehicles.form.badges).toEqual({
      required: "\u0645\u0637\u0644\u0648\u0628",
      optional: "\u0627\u062e\u062a\u064a\u0627\u0631\u064a",
      default: "\u0627\u0641\u062a\u0631\u0627\u0636\u064a",
    });
    expect(representativesVehicles.en.vehicles.form.badges).toEqual({
      required: "Required", optional: "Optional", default: "Default",
    });
    expect(representativesVehicles.ar.vehicles.fields.nextMaintenanceDate).toBe(
      "\u0645\u0648\u0639\u062f \u0627\u0644\u0635\u064a\u0627\u0646\u0629 \u0627\u0644\u0642\u0627\u062f\u0645\u0629",
    );
    expect(representativesVehicles.en.vehicles.fields.nextMaintenanceDate).toBe("Next maintenance date");
  });
});
