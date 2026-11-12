import { webcrypto } from "node:crypto";
import type { ReactNode } from "react";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouteLifecyclePanel } from "@/features/dispatch/routeLifecycle/RouteLifecyclePanel";
import type { PendingRoute } from "@/types/dispatch";

vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children, title }: {
    isOpen: boolean; children: ReactNode; title: string;
  }) => isOpen ? <div role="dialog" aria-label={title}>{children}</div> : null,
}));
vi.mock("@/components/ui/custom-select", () => ({
  CustomSelect: ({ label, options, value, onChange, disabled }: {
    label: string; options: Array<{id: string; label: string}>;
    value: string; onChange: (id: string) => void; disabled: boolean;
  }) => <select aria-label={label} value={value}
    disabled={disabled} onChange={e => onChange(e.target.value)}>
    {options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
  </select>,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { language: "ar", dir: () => "rtl" } }),
}));

const route: PendingRoute = {
  id: "17", zoneId: "9", zoneName: "الشمال", driverId: "4", driverName: "تاريخي",
  vehicleId: "5", shopsRemaining: 3, sourceWarehouseId: "12",
  status: "postponed", sessionBound: true, sessionEnded: true,
  adjustmentContextRevision: 99, assignmentContextRevision: 3,
  currentPeriodId: null, currentDriverId: null, currentVehicleId: null,
  currentVehicleLocationId: null,
  can_execute: true, commercial_context: null,
};

const proof = {
  routeId: 17, assignmentRevision: 3,
  currentPeriodId: null, currentDriverId: null, currentVehicleId: null,
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("crypto", webcrypto);
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: async (_key: string, _opts: unknown,
      perform: (lock: object) => Promise<unknown>) => perform({}) },
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
});

describe("M05 signed operational route panel", () => {
  it("does not send RESUME before a current accepted target custody proof, then posts exact M02 intent", async () => {
    const requests: Array<{path: string; data: Record<string, unknown> | null}> = [];
    let ready = false;
    const fetch = vi.fn(async (path: string, init?: RequestInit) => {
      requests.push({ path, data: init?.body ? JSON.parse(String(init.body)) : null });
      if (path.includes("/readiness")) {
        if (!ready) throw Object.assign(new Error("not authorized"), { status: 409 });
        return { driverId: 7, vehicleId: 6, custodyRevision: 12,
          assignmentContextRevision: 3, accepted: true, authorized: true };
      }
      const body = JSON.parse(String(init?.body));
      return { state: "COMMITTED", request_id: body.request_id,
        route_id: 17, action: "RESUME", status: "active",
        context_revision: 4, zone_reserved: true, live_assets_reserved: true };
    });
    const onCommitted = vi.fn();
    const props = {
      isOpen: true, onClose: vi.fn(), route, assignment: proof,
      drivers: [{ id: "7", label: "مندوب موثق" }],
      vehicles: [{ id: "6", label: "سيارة موثقة" }],
      selectedDriver: "7", selectedVehicle: "6",
      onDriverChange: vi.fn(), onVehicleChange: vi.fn(),
      actorScope: "1:2:3", fetch, authorized: () => true,
      onCommitted, initialAction: "RESUME" as const,
    };
    const view = render(<RouteLifecyclePanel {...props} />);
    const resume = screen.getByRole("button", { name: "استئناف الخط" });
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(resume).toBeDisabled();
    expect(requests.every(r => r.data === null)).toBe(true);
    ready = true;
    view.rerender(<RouteLifecyclePanel {...props} selectedVehicle="" />);
    view.rerender(<RouteLifecyclePanel {...props} />);
    await waitFor(() => expect(resume).toBeEnabled());
    fireEvent.click(resume);
    await waitFor(() => expect(onCommitted).toHaveBeenCalledTimes(1));
    const writes = requests.filter(r => r.data);
    expect(writes).toHaveLength(1);
    expect(writes[0].path).toBe("/dispatch/route/17/lifecycle");
    expect(writes[0].data).toMatchObject({
      action: "RESUME", expected_context_revision: 3,
      expected_period_id: null, expected_vehicle_custody_revision: 12,
      target_driver_id: 7, target_vehicle_id: 6,
    });
  });

  it("revoked execute scope disables route actions before probe or mutation", async () => {
    const fetch = vi.fn(async () => ({}));
    render(<RouteLifecyclePanel isOpen onClose={() => undefined}
      route={{ ...route, can_execute: false }} assignment={proof}
      drivers={[]} vehicles={[]} selectedDriver="" selectedVehicle=""
      onDriverChange={() => undefined} onVehicleChange={() => undefined}
      actorScope="1:2:3" fetch={fetch} authorized={() => false}
      initialAction="RESUME" onCommitted={() => undefined} />);
    expect(screen.getByRole("button", { name: "استئناف الخط" })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });
});
