import { beforeAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";
import { vehicleErrorMessage } from "./vehicleErrorMessage";

const coded = (code: string) => Object.assign(new Error(code), { code, status: 409 });

describe("Vehicle merged backend error codes", () => {
  beforeAll(async () => {
    await i18n.changeLanguage("en");
  });

  it.each([
    "VEHICLE_CUSTODY_LOCATION_MISSING",
    "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS",
    "VEHICLE_CUSTODY_LOCATION_INCONSISTENT",
  ])("maps %s to business copy instead of exposing the raw code", (code) => {
    const message = vehicleErrorMessage(coded(code), "fallback");
    expect(message).toContain("Vehicle stock is not ready for operation");
    expect(message).not.toContain(code);
  });

  it("maps optimistic version conflicts clearly", () => {
    expect(vehicleErrorMessage(coded("VEHICLE_VERSION_CONFLICT"), "fallback")).toBe(
      "This vehicle changed elsewhere. Refresh the list and try again.",
    );
  });
});
