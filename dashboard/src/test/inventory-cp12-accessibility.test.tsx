import { useRef, useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Boxes, Truck } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { useDialogFocusTrap } from "@/hooks/useDialogFocusTrap";
import { InventoryTopDock } from "@/pages/inventory/InventoryTopDock";

vi.mock("@/pages/inventory/inventoryTopDockController", () => ({
  createInventoryTopDockController: () => () => undefined,
}));

const dockItems = [
  { id: "live", label: "Live Stock", icon: Boxes },
  { id: "transfers", label: "Transfers", icon: Truck },
] as const;

function DialogHarness() {
  const [open, setOpen] = useState(false);
  const initialFocusRef = useRef<HTMLInputElement | null>(null);
  const dialogRef = useDialogFocusTrap<HTMLDivElement>(open, () => setOpen(false), initialFocusRef);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      {open ? (
        <div ref={dialogRef} role="dialog" aria-modal="true" tabIndex={-1}>
          <div className="app-modal-body" tabIndex={-1}>
            <input ref={initialFocusRef} aria-label="First field" />
            <button type="button">Last action</button>
          </div>
        </div>
      ) : null}
    </>
  );
}

describe("CP12 Inventory accessibility closure", () => {
  it("supports LTR roving tab navigation with logical arrow/Home/End keys", () => {
    const onChange = vi.fn();
    render(
      <div dir="ltr">
        <InventoryTopDock
          items={dockItems}
          activeId="live"
          ariaLabel="Inventory sections"
          onChange={onChange}
        />
      </div>,
    );

    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");

    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("transfers");

    fireEvent.keyDown(tabs[1], { key: "Home" });
    expect(tabs[0]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("live");

    fireEvent.keyDown(tabs[0], { key: "End" });
    expect(tabs[1]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("transfers");
  });

  it("mirrors horizontal keyboard navigation under RTL without reversing semantics", () => {
    const onChange = vi.fn();
    render(
      <div dir="rtl">
        <InventoryTopDock
          items={dockItems}
          activeId="live"
          ariaLabel="أقسام المخزون"
          onChange={onChange}
        />
      </div>,
    );

    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("transfers");

    fireEvent.keyDown(tabs[1], { key: "ArrowLeft" });
    expect(tabs[0]).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("live");
  });

  it("focuses dialog content, traps Tab and Shift+Tab, closes on Escape, and restores focus", async () => {
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    trigger.focus();
    fireEvent.click(trigger);

    const first = await screen.findByRole("textbox", { name: "First field" });
    await waitFor(() => expect(first).toHaveFocus());

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Last action" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps Inventory dock controls natively named and icon decoration hidden", () => {
    render(
      <div dir="ltr">
        <InventoryTopDock
          items={dockItems}
          activeId="live"
          ariaLabel="Inventory sections"
          onChange={() => undefined}
        />
      </div>,
    );

    expect(screen.getByRole("tablist", { name: "Inventory sections" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Live Stock" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Transfers" })).toBeInTheDocument();
    for (const icon of document.querySelectorAll(".inventory-top-dock__icon")) {
      expect(icon).toHaveAttribute("aria-hidden", "true");
    }
  });
});
