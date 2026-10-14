from pathlib import Path

modal = Path('dashboard/src/components/ui/modal.tsx')
text = modal.read_text(encoding='utf-8')
old = 'import { useId } from "react";\nimport { motion, AnimatePresence } from "framer-motion";'
new = 'import { useId } from "react";\nimport { createPortal } from "react-dom";\nimport { motion, AnimatePresence } from "framer-motion";'
assert old in text
text = text.replace(old, new, 1)
old = '  return (\n    <AnimatePresence>'
new = '  if (typeof document === "undefined") return null;\n\n  return createPortal(\n    <AnimatePresence>'
assert old in text
text = text.replace(old, new, 1)
old = '    </AnimatePresence>\n  );\n}'
new = '    </AnimatePresence>,\n    document.body,\n  );\n}'
assert old in text
text = text.replace(old, new, 1)
modal.write_text(text, encoding='utf-8')

form = Path('dashboard/src/pages/representatives-vehicles/representatives/RepresentativeForm.tsx')
text = form.read_text(encoding='utf-8')
old = '            <p id="representative-debt-hint" className="text-[11px] font-semibold leading-5 text-slate-500">{t("representativesVehicles.representatives.form.debtHint")}</p>'
new = '            <span id="representative-debt-hint" className="sr-only">{t("representativesVehicles.representatives.form.debtA11yHint")}</span>'
assert old in text
text = text.replace(old, new, 1)
form.write_text(text, encoding='utf-8')

i18n = Path('dashboard/src/i18n/representativesVehicles.ts')
text = i18n.read_text(encoding='utf-8')
replacements = {
    'usernameHint: "استخدم أحرفًا عربية أو إنجليزية، ويمكن إضافة الأرقام و . _ - دون خلط العربية والإنجليزية في الاسم نفسه.",': 'usernameHint: "استخدم العربية أو الإنجليزية دون خلط، ويمكن إضافة الأرقام و . _ -",',
    'debtHint: "هذا الحد هو أقصى مبلغ ذمم جديد في عملية بيع واحدة. ليس حدًا يوميًا ولا يتجدد تلقائيًا، ويظل سقف ذمة المحل مطبقًا بشكل مستقل.",': 'debtA11yHint: "الحد الأقصى للذمم الجديدة في عملية بيع واحدة.",',
    'debtLimit: "Per-sale credit limit",': 'debtLimit: "Debt limit per sale",',
    'usernameHint: "Use Arabic or Latin letters, optionally with numbers and . _ -. Do not mix Arabic and Latin letters in the same username.",': 'usernameHint: "Use Arabic or Latin letters without mixing them; numbers and . _ - are allowed.",',
    'debtHint: "This is the maximum new credit for a single sale. It is not a daily limit and does not reset automatically. The shop’s total credit limit still applies independently.",': 'debtA11yHint: "Maximum new debt for one sale.",',
}
for old, new in replacements.items():
    assert old in text, old
    text = text.replace(old, new, 1)
i18n.write_text(text, encoding='utf-8')

tests = Path('dashboard/src/pages/representatives-vehicles/representatives/RepresentativeForm.test.tsx')
text = tests.read_text(encoding='utf-8')
old = '''  it("keeps disabled credit limit hidden and reveals an empty localized input", () => {
    render(<RepresentativeForm onCancel={() => undefined} onSubmit={vi.fn()} />);
    expect(screen.queryByLabelText(field.debtLimit)).toBeNull();
    fireEvent.click(screen.getByLabelText(field.debtPermission));
    const limit = screen.getByLabelText(field.debtLimit) as HTMLInputElement;
    expect(limit.value).toBe("");
    expect(limit.placeholder).toBe("مثال: 50.000");
  });'''
new = '''  it("keeps disabled credit limit hidden and reveals a compact accessible input", () => {
    render(<RepresentativeForm onCancel={() => undefined} onSubmit={vi.fn()} />);
    expect(screen.queryByLabelText(field.debtLimit)).toBeNull();
    fireEvent.click(screen.getByLabelText(field.debtPermission));
    const limit = screen.getByLabelText(field.debtLimit) as HTMLInputElement;
    expect(limit.value).toBe("");
    expect(limit.placeholder).toBe("مثال: 50.000");
    expect(limit).toHaveAttribute("aria-describedby", "representative-debt-hint");
    expect(screen.getByText("representativesVehicles.representatives.form.debtA11yHint")).toHaveClass("sr-only");
    expect(screen.queryByText("representativesVehicles.representatives.form.debtHint")).toBeNull();
  });'''
assert old in text
text = text.replace(old, new, 1)
old = '''describe("Representative final form copy", () => {
  it("keeps accepted credit semantics in Arabic and English", () => {
    const ar = representativesVehicles.ar.representatives.form.debtHint;
    const en = representativesVehicles.en.representatives.form.debtHint;
    expect(ar).toContain("عملية بيع واحدة");
    expect(ar).toContain("ليس حدًا يوميًا");
    expect(ar).toContain("لا يتجدد تلقائيًا");
    expect(ar).toContain("سقف ذمة المحل");
    expect(en).toContain("single sale");
    expect(en).toContain("not a daily limit");
    expect(en).toContain("does not reset automatically");
  });

  it("has required phone and equal-status Arabic username copy", () => {
    expect(representativesVehicles.ar.representatives.form.phoneRequired).toBe("أدخل رقم هاتف المندوب.");
    expect(representativesVehicles.en.representatives.form.phoneRequired).toBe("Enter the representative’s phone number.");
    expect(representativesVehicles.ar.representatives.form.usernameHint).toContain("أحرفًا عربية أو إنجليزية");
    expect(representativesVehicles.en.representatives.form.usernameHint).toContain("Arabic or Latin letters");
  });
});'''
new = '''describe("Representative final form copy", () => {
  it("uses the exact compact username helper in Arabic and English", () => {
    expect(representativesVehicles.ar.representatives.form.usernameHint).toBe(
      "استخدم العربية أو الإنجليزية دون خلط، ويمكن إضافة الأرقام و . _ -",
    );
    expect(representativesVehicles.en.representatives.form.usernameHint).toBe(
      "Use Arabic or Latin letters without mixing them; numbers and . _ - are allowed.",
    );
    expect(JSON.stringify(representativesVehicles)).not.toContain(
      "استخدم أحرفًا عربية أو إنجليزية، ويمكن إضافة الأرقام و . _ - دون خلط العربية والإنجليزية في الاسم نفسه.",
    );
  });

  it("removes the visible debt paragraph while preserving the concise business label and a11y description", () => {
    expect("debtHint" in representativesVehicles.ar.representatives.form).toBe(false);
    expect("debtHint" in representativesVehicles.en.representatives.form).toBe(false);
    expect(representativesVehicles.ar.representatives.fields.debtLimit).toBe("حد الذمم لكل عملية بيع");
    expect(representativesVehicles.en.representatives.fields.debtLimit).toBe("Debt limit per sale");
    expect(representativesVehicles.ar.representatives.form.debtA11yHint).toBe("الحد الأقصى للذمم الجديدة في عملية بيع واحدة.");
    expect(representativesVehicles.en.representatives.form.debtA11yHint).toBe("Maximum new debt for one sale.");
    expect(JSON.stringify(representativesVehicles)).not.toContain(
      "هذا الحد هو أقصى مبلغ ذمم جديد في عملية بيع واحدة. ليس حدًا يوميًا ولا يتجدد تلقائيًا، ويظل سقف ذمة المحل مطبقًا بشكل مستقل.",
    );
  });

  it("keeps required phone copy unchanged", () => {
    expect(representativesVehicles.ar.representatives.form.phoneRequired).toBe("أدخل رقم هاتف المندوب.");
    expect(representativesVehicles.en.representatives.form.phoneRequired).toBe("Enter the representative’s phone number.");
  });
});'''
assert old in text
text = text.replace(old, new, 1)
tests.write_text(text, encoding='utf-8')

modal_test = Path('dashboard/src/components/ui/modal.test.tsx')
modal_test.write_text('''import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => "rtl" },
  }),
}));

import { Modal } from "./modal";

afterEach(cleanup);

describe("Modal portal layering contract", () => {
  it("portals the fixed z-50 layer to document.body outside a lower page stacking context", () => {
    const onClose = vi.fn();
    const { container } = render(
      <div className="relative z-10" data-testid="page-stack">
        <header className="sticky z-40" data-testid="app-header">header</header>
        <Modal isOpen onClose={onClose} title="Create representative">
          <button type="button">first body action</button>
        </Modal>
      </div>,
    );

    const layer = document.querySelector<HTMLElement>(".app-modal");
    expect(layer).not.toBeNull();
    expect(layer?.parentElement).toBe(document.body);
    expect(container.querySelector(".app-modal")).toBeNull();
    expect(layer?.className).toContain("fixed");
    expect(layer?.className).toContain("inset-0");
    expect(layer?.className).toContain("z-50");
    expect(screen.getByTestId("app-header").className).toContain("z-40");
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-labelledby");
  });

  it("preserves outside-click and Escape dismissal through the portal", () => {
    const onClose = vi.fn();
    render(
      <Modal isOpen onClose={onClose} title="Representative status">
        <button type="button">body action</button>
      </Modal>,
    );
    fireEvent.click(document.querySelector(".app-modal-backdrop")!);
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
''', encoding='utf-8')
