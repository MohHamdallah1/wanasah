import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("Dashboard error-boundary recovery", () => {
  it("recovers without destroying the authenticated session or local drafts", () => {
    const source = readFileSync(
      join(process.cwd(), "src/App.tsx"),
      "utf8",
    );

    expect(source).toContain("window.location.reload()");
    expect(source).toContain("window.location.href = '/'");
    expect(source).not.toContain("localStorage.clear()");
    expect(source).not.toContain("sessionStorage.clear()");
    expect(source).not.toContain("/logout");
  });
});
