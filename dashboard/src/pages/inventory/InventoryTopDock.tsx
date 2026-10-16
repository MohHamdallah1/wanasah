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
  className?: string;
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
  className = "",
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
    tabs[normalized]?.focus();
    onChange(nextItem.id);
  };

  return (
    <WorkspaceTopBar
      variant="dock"
      className={`inventory-top-dock-component${
        className ? ` ${className}` : ""
      }`}
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
        role="tablist"
        data-dock-state="idle"
        data-dock-max="0.00"
      >
        {items.map(({ id, label, icon }, index) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={activeId === id}
            tabIndex={activeId === id ? 0 : -1}
            data-inventory-dock-item
            className="inventory-top-dock__item focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
            onClick={() => onChange(id)}
            onKeyDown={(event) => moveFocus(event, index)}
          >
            <DockIcon icon={icon} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </WorkspaceTopBar>
  );
}
