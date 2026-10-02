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

describe("Products P9.4 tracking workspace", () => {
  it("presents the three existing tracking modes as one accessible compact decision control", () => {
    const picker = read(
      "../pages/products/tracking/ProductTrackingModePicker.tsx",
    );

    expect(picker).toContain(
      'role="radiogroup"',
    );
    expect(picker).toContain(
      'role="radio"',
    );
    expect(picker).toContain(
      "aria-checked={selected}",
    );
    expect(picker).toContain(
      '"NONE"',
    );
    expect(picker).toContain(
      '"OPTIONAL"',
    );
    expect(picker).toContain(
      '"REQUIRED"',
    );
    expect(picker).toContain(
      "onChange(mode)",
    );
    expect(picker).not.toContain(
      "<select",
    );
  });

  it("keeps tracking fields presentation-only and delegates existing values and callbacks", () => {
    const fields = read(
      "../pages/products/tracking/ProductTrackingFields.tsx",
    );

    expect(fields).toContain(
      'kind="lot"',
    );
    expect(fields).toContain(
      'kind="expiry"',
    );
    expect(fields).toContain(
      "value={lotControlMode}",
    );
    expect(fields).toContain(
      "value={expiryControlMode}",
    );
    expect(fields).toContain(
      "onLotControlModeChange",
    );
    expect(fields).toContain(
      "onExpiryControlModeChange",
    );
    expect(fields).not.toContain(
      "fetch(",
    );
    expect(fields).not.toContain(
      "useMutation",
    );
  });

  it("keeps the common path to required-or-optional and leaves NONE in advanced controls", () => {
    const simple = read(
      "../pages/products/tracking/ProductTrackingSimpleControls.tsx",
    );

    expect(simple).toContain(
      'role="switch"',
    );
    expect(simple).toContain(
      '"OPTIONAL"',
    );
    expect(simple).toContain(
      '"REQUIRED"',
    );
    expect(simple).toContain(
      'mode === "NONE"',
    );
    expect(simple).toContain(
      "<ProductTrackingFields",
    );
  });

  it("keeps company defaults plain-language while per-product tracking retains safety guidance", () => {
    const settings = read(
      "../pages/products/tracking/ProductTrackingSettings.tsx",
    );
    const editor = read(
      "../pages/products/tracking/ProductTrackingEditor.tsx",
    );

    expect(settings).not.toContain(
      "lotControlSource",
    );
    expect(settings).not.toContain(
      "expiryControlSource",
    );
    expect(settings).not.toContain(
      '"products.trackingSettings.companySource"',
    );
    expect(settings).not.toContain(
      '"products.trackingSettings.platformSource"',
    );
    expect(settings).toContain(
      '"products.trackingSettings.description"',
    );

    expect(editor).toContain(
      '"products.trackingEditor.warning"',
    );
    expect(editor).toContain(
      '"products.trackingEditor.lockHint"',
    );
    expect(editor).toContain(
      "const changed =",
    );
    expect(editor).toContain(
      "!changed",
    );
  });

  it("keeps the new tracking UI dense without hiding the selected rule explanation", () => {
    const picker = read(
      "../pages/products/tracking/ProductTrackingModePicker.tsx",
    );
    const settings = read(
      "../pages/products/tracking/ProductTrackingSettings.tsx",
    );

    expect(picker).toContain(
      "grid grid-cols-3",
    );
    expect(picker).toContain(
      "products.tracking.shortModes.",
    );
    expect(picker).toContain(
      "modeFamily",
    );
    expect(settings).toContain(
      "space-y-3",
    );
    expect(settings).not.toContain(
      "rounded-2xl bg-sky-50 p-4",
    );
  });
});
