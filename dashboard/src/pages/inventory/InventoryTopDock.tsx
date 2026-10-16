import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import type { LucideIcon } from "lucide-react";

import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import {
  createInventoryTopDockController,
  type InventoryTopDockOptions,
} from "./inventoryTopDockController";
import "./inventoryShellPolish.css";

type InventoryDockItem = {
  id: string;
  label: string;
  icon: LucideIcon;
};

interface InventoryTopDockProps {
  items: readonly InventoryDockItem[];
  activeId: string;
  ariaLabel: string;
  onChange: (id: string) => void;
}

const OPTIONS: InventoryTopDockOptions = {
  proximity: 95,
  spring: 0.16,
  damping: 0.55,
  widthGrowth: 0,
  heightGrowth: 4,
  drop: 0.7,
  lockTrack: true,
};

function useInventoryDockController() {
  const rootRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;

    return createInventoryTopDockController(
      root,
      () => OPTIONS,
    );
  }, []);

  return rootRef;
}

function DockIcon({
  icon: Icon,
}: {
  icon: LucideIcon;
}): ReactNode {
  return (
    <span
      className="inventory-top-dock__icon"
      aria-hidden="true"
    >
      <Icon />
    </span>
  );
}

export function InventoryTopDock({
  items,
  activeId,
  ariaLabel,
  onChange,
}: InventoryTopDockProps) {
  const rootRef = useInventoryDockController();

  const moveFocus = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    if (!items.length) return;

    const root = rootRef.current;
    if (!root) return;

    const inheritedDir = root.closest<HTMLElement>("[dir]")?.getAttribute("dir");
    const isRtl = inheritedDir === "rtl" || (
      inheritedDir !== "ltr" && window.getComputedStyle(root).direction === "rtl"
    );
    let nextIndex: number | null = null;

    if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = items.length - 1;
    else if (event.key === "ArrowRight") {
      nextIndex = currentIndex + (isRtl ? -1 : 1);
    } else if (event.key === "ArrowLeft") {
      nextIndex = currentIndex + (isRtl ? 1 : -1);
    } else {
      return;
    }

    event.preventDefault();
    const normalized = (nextIndex + items.length) % items.length;
    const nextItem = items[normalized];
    const tabs = root.querySelectorAll<HTMLButtonElement>("[role='tab']");
    const nextTab = tabs[normalized];
    nextTab?.focus();
    nextTab?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    onChange(nextItem.id);
  };

  return (
    <WorkspaceTopBar
      variant="dock"
      data-dock-frame
    >
      <div
        className="inventory-top-dock__aurora"
        aria-hidden="true"
      />
      <nav
        ref={rootRef}
        className="inventory-top-dock__dock"
        aria-label={ariaLabel}
        aria-orientation="horizontal"
        role="tablist"
        data-dock-state="idle"
        data-dock-max="0.00"
      >
        {items.map(({ id, label, icon }, index) => {
          const active = activeId === id;
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
              className="inventory-top-dock__item focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
              title={label}
              onClick={() => onChange(id)}
              onKeyDown={(event) => moveFocus(event, index)}
            >
              <DockIcon icon={icon} />
              <span className="inventory-top-dock__label">{label}</span>
            </button>
          );
        })}
      </nav>
    </WorkspaceTopBar>
  );
}
