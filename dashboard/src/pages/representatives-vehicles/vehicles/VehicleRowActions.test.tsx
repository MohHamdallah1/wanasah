import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Vehicle } from "./contracts";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { plate?: string }) => {
      if (key.endsWith("actionsMenu")) return "actions:" + options?.plate;
      if (key.endsWith("details.action")) return "details";
      if (key.endsWith("load.action")) return "load";
      if (key.endsWith("edit")) return "edit";
      if (key.endsWith("lifecycle.deactivate")) return "deactivate";
      if (key.endsWith("lifecycle.reactivate")) return "reactivate";
      if (key.endsWith("permissions.manageRequired")) return "manage-blocked";
      return key;
    },
  }),
}));

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuSeparator: () => <hr />,
  DropdownMenuItem: ({
    children,
    disabled,
    onSelect,
    ...props
  }: {
    children: ReactNode;
    disabled?: boolean;
    onSelect?: () => void;
  } & HTMLAttributes<HTMLButtonElement>) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onSelect?.()}
      {...(props as ButtonHTMLAttributes<HTMLButtonElement>)}
    >
      {children}
    </button>
  ),
}));

import { VehicleRowActions } from "./VehicleRowActions";

const vehicle: Vehicle = {
  id: 7,
  plate_number: "12-34567",
  vehicle_type: "Van",
  current_mileage: 1000,
  next_oil_change: null,
  license_expiry_date: null,
  next_maintenance_date: null,
  maintenance_status: "Active",
  is_active: true,
  version: 1,
  custody_ready: true,
};

afterEach(cleanup);

describe("VehicleRowActions", () => {
  it("keeps Load available without vehicle.manage while CRUD actions remain gated", () => {
    const onView = vi.fn();
    const onLoad = vi.fn();
    const onEdit = vi.fn();
    const onLifecycle = vi.fn();

    render(
      <VehicleRowActions
        vehicle={vehicle}
        canManage={false}
        onView={onView}
        onLoad={onLoad}
        onEdit={onEdit}
        onLifecycle={onLifecycle}
      />,
    );

    expect(screen.getByRole("button", { name: "actions:12-34567" })).toBeTruthy();
    expect(screen.getByText("details")).not.toBeDisabled();
    expect(screen.getByText("load")).not.toBeDisabled();
    expect(screen.getByText("edit")).toBeDisabled();
    expect(screen.getByText("deactivate")).toBeDisabled();

    fireEvent.click(screen.getByText("load"));
    expect(onLoad).toHaveBeenCalledWith(vehicle);
    expect(onEdit).not.toHaveBeenCalled();
    expect(onLifecycle).not.toHaveBeenCalled();
  });

  it("keeps normal Vehicle CRUD actions available when vehicle.manage is present", () => {
    render(
      <VehicleRowActions
        vehicle={{ ...vehicle, is_active: false }}
        canManage
        onView={vi.fn()}
        onLoad={vi.fn()}
        onEdit={vi.fn()}
        onLifecycle={vi.fn()}
      />,
    );

    expect(screen.getByText("load")).not.toBeDisabled();
    expect(screen.getByText("edit")).not.toBeDisabled();
    expect(screen.getByText("reactivate")).not.toBeDisabled();
  });
});
