import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

import { WorkspaceTopBar } from "@/components/workspace/WorkspaceTopBar";
import { cn } from "@/lib/utils";
import { createInventoryTopDockController } from "./inventoryTopDockController";
import "./inventoryShellPolish.css";

type DockItem = {
  id: string;
  label: string;
  icon: ReactNode;
};

type InventoryTopDockProps = {
  items: readonly DockItem[];
  activeId: string;
  ariaLabel: string;
  onChange: (id: string) => void;
  className?: string;
};

const normalizeIndex = (index: number, length: number) =>
  ((index % length) + length) % length;

export function InventoryTopDock({
  items,
  activeId,
  ariaLabel,
  onChange,
  className,
}: InventoryTopDockProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const root = rootRef.current;
    if (!root || items.length === 0) return;

    return createInventoryTopDockController({
      root,
      activeId,
      itemCount: items.length,
      onSelect: (index) => {
        const item = items[index];
        if (item) onChangeRef.current(item.id);
      },
    });
  }, [activeId, items]);

  const moveFocus = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    if (items.length < 2) return;

    const direction =
      event.currentTarget.closest<HTMLElement>("[dir]")?.dir ||
      window.getComputedStyle(event.currentTarget).direction;
    const rtl = direction === "rtl";
    let nextIndex: number | null = null;

    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = items.length - 1;
    if (event.key === "ArrowRight") {
      nextIndex = currentIndex + (rtl ? -1 : 1);
    }
    if (event.key === "ArrowLeft") {
      nextIndex = currentIndex + (rtl ? 1 : -1);
    }
    if (nextIndex === null) return;

    event.preventDefault();
    const normalized = normalizeIndex(nextIndex, items.length);
    const tab = rootRef.current?.querySelectorAll<HTMLButtonElement>(
      "[data-inventory-dock-item]",
    )[normalized];
    tab?.focus();
    tab?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    const nextItem = items[normalized];
    if (nextItem) onChange(nextItem.id);
  };

  return (
    <WorkspaceTopBar
      variant="dock"
      ref={rootRef}
      className={cn("inventory-top-dock-component", className)}
      data-dock-frame
    >
      <div className="inventory-top-dock__aurora" aria-hidden="true" />
      <nav
        className="inventory-top-dock__dock"
        role="tablist"
        aria-label={ariaLabel}
        aria-orientation="horizontal"
      >
        {items.map(({ id, label, icon }, index) => {
          const active = id === activeId;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-current={active ? "page" : undefined}
              tabIndex={active ? 0 : -1}
              data-inventory-dock-item
              data-active={active ? "true" : "false"}
              className="inventory-top-dock__item focus-visible:outline-none"
              title={label}
              onClick={() => onChange(id)}
              onKeyDown={(event) => moveFocus(event, index)}
            >
              <span className="inventory-top-dock__icon" aria-hidden="true">
                {icon}
              </span>
              <span className="inventory-top-dock__label">{label}</span>
            </button>
          );
        })}
      </nav>
    </WorkspaceTopBar>
  );
}
