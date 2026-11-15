import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("navigation active contrast on operations-to-products route switch", () => {
  it("keeps visible labels, stable keyed elements and no interpolated gold/dark active state", () => {
    const src = read("src/components/operations/OperationsSidebar.tsx");
    const css = read("src/components/operations/dashboard.css");
    expect(src).toContain('path: "/representatives-vehicles"');
    expect(src).toContain('path: "/products"');
    expect(src).toContain("key={item.path}");
    expect(src).toContain("{t(item.labelKey)}");
    expect(src).toContain("operations-nav-item flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-none");
    expect(src).not.toContain("text-sm font-medium transition-all duration-200");
    expect(css).toContain('.operations-nav-item[data-active="true"]');
    expect(css).toContain("border-color: rgb(245 189 52 / 0.45)");
  });
});
