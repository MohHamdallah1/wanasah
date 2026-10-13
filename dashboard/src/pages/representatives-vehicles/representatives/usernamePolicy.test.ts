import { describe, expect, it } from "vitest";

import { isRepresentativeUsernameValid } from "./usernamePolicy";

describe("Representative username policy", () => {
  it.each([
    "محمد",
    "محمد12",
    "مندوب_12",
    "mohammad",
    "mohammad12",
    "rep_12",
    "rep-12",
    "rep.12",
  ])("accepts %s", (username) => {
    expect(isRepresentativeUsernameValid(username)).toBe(true);
  });

  it.each([
    "محمدmohammad",
    "repمحمد",
    "مohammad",
    "123456",
    "._-",
    "rep 12",
    "مندوب 12",
  ])("rejects %s", (username) => {
    expect(isRepresentativeUsernameValid(username)).toBe(false);
  });

  it("allows normal outer trim without rewriting the username body", () => {
    expect(isRepresentativeUsernameValid("  مندوب_12  ")).toBe(true);
  });
});
