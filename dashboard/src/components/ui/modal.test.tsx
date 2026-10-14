import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
