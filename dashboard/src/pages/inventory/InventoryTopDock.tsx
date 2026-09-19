import {
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import type { LucideIcon } from "lucide-react";
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

  return (
    <div
      className={`inventory-top-dock-component${
        className ? ` ${className}` : ""
      }`}
      data-dock-frame
    >
      <div
        className="inventory-top-dock__aurora"
        aria-hidden="true"
      />

      <div className="inventory-top-dock__bar">
        <nav
          ref={rootRef}
          className="inventory-top-dock__dock"
          aria-label={ariaLabel}
          role="tablist"
          data-dock-state="idle"
          data-dock-max="0.00"
        >
          {items.map(({ id, label, icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={activeId === id}
              data-inventory-dock-item
              className="inventory-top-dock__item"
              onClick={() => onChange(id)}
            >
              <DockIcon icon={icon} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
