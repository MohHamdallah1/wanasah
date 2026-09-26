import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products P9.4 detail drawer", () => {
  it("is closed by page state and supports bounded compact and expanded desktop widths", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );

    expect(drawer).toContain(
      "if (!product)",
    );
    expect(drawer).toContain(
      "sm:w-[min(44vw,620px)]",
    );
    expect(drawer).toContain(
      "sm:w-[min(72vw,920px)]",
    );
    expect(drawer).toContain(
      "aria-pressed={",
    );
    expect(drawer).toContain(
      '"products.details.expand"',
    );
    expect(drawer).toContain(
      '"products.details.compact"',
    );
  });

  it("resets expansion on close and stays full width on narrow screens", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );

    expect(drawer).toContain(
      "setExpanded(false);",
    );
    expect(drawer).toContain(
      "onClick={handleClose}",
    );
    expect(drawer).toContain(
      "flex w-full flex-col",
    );
    expect(drawer).toContain(
      "sm:inline-flex",
    );
  });

  it("keeps details view-first while preserving all mutation permissions in one compact actions surface", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );
    const actions = read(
      "../pages/products/detail/ProductDetailActionsMenu.tsx",
    );
    const primitives = read(
      "../pages/products/detail/ProductDetailPrimitives.tsx",
    );

    expect(drawer).toContain(
      "<ProductDetailActionsMenu",
    );
    expect(drawer).not.toContain(
      "<footer",
    );
    expect(drawer).not.toContain(
      'className="rounded-2xl border border-slate-200 p-4"',
    );

    expect(actions).toContain(
      "canRenameProduct &&",
    );
    expect(actions).toContain(
      "canReassignFamily &&",
    );
    expect(actions).toContain(
      "canEditPrice &&",
    );
    expect(actions).toContain(
      "{canEditTracking ? (",
    );
    expect(actions).toContain(
      "{canManageBarcodes ? (",
    );
    expect(actions).toContain(
      "{canManageLifecycle ? (",
    );
    expect(actions).toContain(
      "canManageAdvancedUom &&",
    );

    expect(primitives).toContain(
      "border-b border-slate-100",
    );
    expect(primitives).not.toContain(
      "rounded-2xl",
    );
  });
});
