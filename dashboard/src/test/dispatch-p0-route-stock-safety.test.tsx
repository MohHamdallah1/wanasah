import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import i18n, { setAppLanguage } from "@/i18n";
import { RouteManagementModal } from "@/components/dispatch/RouteManagementModal";
import { buildRouteStatusOnlyPayload } from "@/features/dispatch/routeStatusPayload";
import type { PendingRoute } from "@/types/dispatch";

vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, title, children, footer }: {
    isOpen: boolean; title: string; children: ReactNode; footer: ReactNode;
  }) => isOpen ? <section role="dialog" aria-label={title}>{children}{footer}</section> : null,
}));
vi.mock("@/components/ui/custom-select", () => ({
  CustomSelect: ({ label, value, onChange, options, disabled }: {
    label: string; value: string; onChange: (id: string) => void;
    options: { id: string; label: string }[]; disabled?: boolean;
  }) => <select aria-label={label || "Representative"} value={value}
    disabled={disabled} onChange={event => onChange(event.target.value)}>
    <option value="">--</option>
    {options.map(opt => <option key={opt.id} value={opt.id}>{opt.label}</option>)}
  </select>,
}));

const route: PendingRoute = {
  id: "9", zoneId: "1", zoneName: "Zone", driverId: "31",
  driverName: "Representative", vehicleId: "17",
  shopsRemaining: 2, status: "waiting", sessionEnded: false,
  sessionBound: false, can_execute: true, commercial_context: null,
};

beforeEach(async () => {
  await setAppLanguage("en");
});

describe("P0 Dispatch route status and physical stock are separate", () => {
  it.each([
    ["active", "31", "17"],
    ["waiting", "32", "23"],
    ["closed", "31", "17"],
    ["postponed", "31", "17"],
  ] as const)("route-only payload %s has no stock field", (status, driver, vehicle) => {
    expect(buildRouteStatusOnlyPayload(status, driver, vehicle))
      .toEqual({ status, driverId: driver, vehicleId: vehicle });
    expect(JSON.stringify(buildRouteStatusOnlyPayload(status, driver, vehicle)))
      .not.toContain("inventory");
  });

  it.each(["ar", "en"] as const)(
    "%s: route confirm never edits stock; separate Adjust Load is explicit",
    async locale => {
      await setAppLanguage(locale);
      const confirm = vi.fn();
      const adjust = vi.fn();
      render(<RouteManagementModal
        isOpen onClose={vi.fn()} routeModalType="follow_up"
        activeRoute={route} drivers={[{ id: "31", name: "Representative" }]}
        transferDriverId="" onTransferDriverChange={vi.fn()}
        vehicles={[{ id: "17", label: "Truck" }]}
        selectedVehicleId="17" onVehicleChange={vi.fn()}
        onConfirmAction={confirm} onAdjustLoad={adjust}
      />);
      expect(screen.queryByRole("spinbutton")).toBeNull();
      expect(screen.getByText(i18n.t("dispatchRouteSafety.separateStock"))).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.title") }));
      expect(adjust).toHaveBeenCalledOnce();
      expect(confirm).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchRouteSafety.confirmRouteOnly") }));
      expect(confirm).toHaveBeenCalledOnce();
    },
  );

  it("never offers physical edit against a newly selected, unassigned vehicle", () => {
    const adjust = vi.fn();
    render(<RouteManagementModal
      isOpen onClose={vi.fn()} routeModalType="transfer"
      activeRoute={route} drivers={[{ id: "32", name: "Other representative" }]}
      transferDriverId="32" onTransferDriverChange={vi.fn()}
      vehicles={[{ id: "17", label: "Truck" }, { id: "23", label: "Other truck" }]}
      selectedVehicleId="23" onVehicleChange={vi.fn()}
      onConfirmAction={vi.fn()} onAdjustLoad={adjust}
    />);
    const button = screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.title") });
    expect(button).toBeDisabled();
    expect(screen.getByText(i18n.t("dispatchRouteSafety.adjustCurrentVehicle"))).toBeVisible();
    fireEvent.click(button);
    expect(adjust).not.toHaveBeenCalled();
  });
});
