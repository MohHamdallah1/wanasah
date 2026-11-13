import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { LaunchResourceSelect } from "@/features/dispatch/launchResources/LaunchResourceSelect";
import { resourceReason } from "@/features/dispatch/launchResources/launchResourceReasons";
import {
  launchAvailabilitySchema, selectionBlocked, useLaunchResourceAvailability,
} from "@/features/dispatch/launchResources/launchResourceRead";
import type { useAuthFetch } from "@/hooks/useAuthFetch";

const language = vi.hoisted(() => ({ current: "ar" }));
vi.mock("react-i18next", async importOriginal => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    i18n: { language: language.current, resolvedLanguage: language.current,
      dir: () => language.current === "ar" ? "rtl" : "ltr" },
  }),
}));
const snapshot = () => ({
  advisory: true as const,
  zones: [{ id: "100", label: "Zone A", available: false,
    code: "ZONE_POSTPONED_RESERVED" as const },
    { id: "101", label: "Zone B", available: true, code: "AVAILABLE" as const },
    { id: "102", label: "Zone C", available: true, code: "AVAILABLE" as const }],
  drivers: [{ id: "10", label: "Ahmed", available: true, code: "AVAILABLE" as const },
    { id: "11", label: "Ali", available: false, code: "REPRESENTATIVE_ON_ROUTE" as const },
    { id: "12", label: "Omar", available: true, code: "AVAILABLE" as const }],
  vehicles: [{ id: "20", label: "Vehicle A", available: true, code: "AVAILABLE" as const },
    { id: "21", label: "Vehicle B", available: false, code: "VEHICLE_ON_ROUTE" as const },
    { id: "22", label: "Vehicle C", available: true, code: "AVAILABLE" as const }],
  warehouses: [{ id: "30", label: "WH", available: true, code: "AVAILABLE" as const },
    { id: "31", label: "WH locked", available: false, code: "WAREHOUSE_AUDIT_LOCK" as const },
    { id: "32", label: "WH alternative", available: true, code: "AVAILABLE" as const }],
});
beforeEach(() => { language.current = "ar"; });
afterEach(() => cleanup());

describe("M05 signed live availability — single four selectors", () => {
  it("POSTPONED reserves Zone A but releases exact Ahmed and Vehicle A, without selectable blocked route", () => {
    const data = launchAvailabilitySchema.parse(snapshot());
    expect(selectionBlocked(data, {
      zoneId: "100", driverId: "10", vehicleId: "20", warehouseId: "30",
    })).toBe(true);
    expect(selectionBlocked(data, {
      zoneId: "101", driverId: "10", vehicleId: "20", warehouseId: "30",
    })).toBe(false);
  });

  // D16: signed backend order is stable within availability groups for all
  // four selectors; blocked options are real disabled controls while the
  // focusable wrapper owns the canonical accessible reason tooltip.
  for (const lang of ["ar", "en"] as const) {
    for (const sample of [
      { kind: "zones" as const, selected: "100", busy: "Zone A",
        available: ["Zone B", "Zone C"], code: "ZONE_POSTPONED_RESERVED" },
      { kind: "drivers" as const, selected: "11", busy: "Ali",
        available: ["Ahmed", "Omar"], code: "REPRESENTATIVE_ON_ROUTE" },
      { kind: "vehicles" as const, selected: "21", busy: "Vehicle B",
        available: ["Vehicle A", "Vehicle C"], code: "VEHICLE_ON_ROUTE" },
      { kind: "warehouses" as const, selected: "31", busy: "WH locked",
        available: ["WH", "WH alternative"], code: "WAREHOUSE_AUDIT_LOCK" },
    ]) {
      it(`D16 ${lang.toUpperCase()} ${sample.kind}: flat available-first, focus/hover reason, selected busy stays inline`, () => {
        language.current = lang;
        const change = vi.fn();
        const options = snapshot()[sample.kind];
        render(<LaunchResourceSelect label={sample.kind} kind={sample.kind} options={options}
          value={sample.selected} onChange={change} disabled={false} placeholder="Select resource" />);
        const root = screen.getByTestId("m05-launch-" + sample.kind);
        const exactReason = resourceReason(sample.code, lang === "ar");
        expect(root).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
        expect(root.querySelector(":scope > p[role=status]")).toBeNull();
        const field = screen.getByRole("button", { name: sample.busy });
        expect(field).toHaveAttribute("aria-describedby");
        const note = document.getElementById(field.getAttribute("aria-describedby")!);
        expect(note).toHaveTextContent(exactReason);
        fireEvent.mouseEnter(field);
        expect(screen.getByRole("tooltip")).toHaveTextContent(exactReason);
        fireEvent.mouseLeave(field);
        expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
        fireEvent.click(field);

        const buttons = screen.getAllByRole("option");
        expect(buttons).toHaveLength(3);
        expect(buttons.map(x => x.getAttribute("aria-label"))).toEqual([
          ...sample.available, sample.busy,
        ]);
        expect(buttons.map(x => x.hasAttribute("disabled"))).toEqual([false, false, true]);
        expect(screen.queryByText(/^Available \(/)).not.toBeInTheDocument();
        expect(screen.queryByText(/^Unavailable \(/)).not.toBeInTheDocument();
        expect(screen.queryByText(/^المتاح \(/)).not.toBeInTheDocument();
        expect(screen.queryByText(/^غير المتاح \(/)).not.toBeInTheDocument();

        const blocked = screen.getByRole("option", { name: sample.busy });
        expect(blocked).toBeDisabled();
        const hintTrigger = blocked.parentElement!;
        expect(hintTrigger).toHaveAttribute("tabindex", "0");
        fireEvent.mouseEnter(hintTrigger);
        expect(screen.getByRole("tooltip")).toHaveTextContent(exactReason);
        fireEvent.mouseLeave(hintTrigger);
        expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
        fireEvent.focus(hintTrigger);
        expect(screen.getByRole("tooltip")).toHaveTextContent(exactReason);
        fireEvent.click(blocked);
        fireEvent.keyDown(hintTrigger, { key: "Enter", code: "Enter" });
        expect(change).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("option", { name: sample.available[0] }));
        expect(change).toHaveBeenCalledExactlyOnceWith(
          options.find(x => x.label === sample.available[0])!.id,
        );
      });
    }
  }

  it("D16 searching stays in stable available-first order and unavailable entries never become enabled", () => {
    language.current = "en";
    const change = vi.fn();
    render(<LaunchResourceSelect label="Vehicle" kind="vehicles" options={snapshot().vehicles}
      value="" onChange={change} disabled={false} placeholder="Select vehicle" />);
    fireEvent.click(screen.getByRole("button", { name: "Select vehicle" }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Vehicle B" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Vehicle B" })).toBeDisabled();
    expect(change).not.toHaveBeenCalled();
  });

  it("D16 disabled but previously signed busy selection keeps a focusable in-field reason, never opens", () => {
    language.current = "en";
    const change = vi.fn();
    render(<LaunchResourceSelect label="Vehicle" kind="vehicles" options={snapshot().vehicles}
      value="21" onChange={change} disabled={true} placeholder="Select vehicle" />);
    const root = screen.getByTestId("m05-launch-vehicles");
    expect(root.querySelector(":scope > p[role=status]")).toBeNull();
    const field = screen.getByRole("button", { name: "Vehicle B" });
    expect(field).toBeDisabled();
    const focusable = field.parentElement!;
    expect(focusable).toHaveAttribute("tabindex", "0");
    fireEvent.focus(focusable);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      resourceReason("VEHICLE_ON_ROUTE", false),
    );
    fireEvent.click(field);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
  });

  it("D16 fail-closed disabled selector does not open or expose previously denied options", () => {
    const change = vi.fn();
    render(<LaunchResourceSelect label="Source warehouse" kind="warehouses" options={[]}
      value="31" onChange={change} disabled={true} placeholder="Select source warehouse" />);
    const field = screen.getByRole("button", { name: "Select source warehouse" });
    expect(field).toBeDisabled();
    fireEvent.click(field);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.queryByText("WH locked")).not.toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
  });

  it("malformed Backend partial/cross-role data never becomes readiness", () => {
    const payload = snapshot();
    expect(launchAvailabilitySchema.safeParse({
      ...payload, drivers: [...payload.drivers, payload.drivers[0]],
    }).success).toBe(false);
    expect(launchAvailabilitySchema.safeParse({
      ...payload, drivers: [{ ...payload.drivers[0], available: true, code: "REPRESENTATIVE_ON_ROUTE" }],
    }).success).toBe(false);
    expect(selectionBlocked(null, {
      zoneId: "101", driverId: "10", vehicleId: "20", warehouseId: "30",
    })).toBe(true);
  });

  it("keeps only same-actor signed option labels warm across SPA return, but blocks commands until fresh Bearer evidence", async () => {
    let finishReentry: ((value: ReturnType<typeof snapshot>) => void) | undefined;
    let reads = 0;
    const fetch = (async () => {
      reads += 1;
      if (reads === 2) return new Promise<ReturnType<typeof snapshot>>(resolve => {
        finishReentry = resolve;
      });
      return snapshot();
    }) as ReturnType<typeof useAuthFetch>;
    const props = { fetch, actorScope: "1:2:3", admitted: true,
      driverId: "10", vehicleId: "20", routeEvidence: "signed-route-1" };
    const { result, rerender } = renderHook(p => useLaunchResourceAvailability(p), {
      initialProps: props,
    });
    await waitFor(() => expect(result.current.fresh).toBe(true));
    rerender({ ...props, admitted: false });
    expect(result.current.fresh).toBe(false);
    expect(result.current.data?.zones[1]?.label).toBe("Zone B");
    rerender({ ...props, admitted: true });
    await waitFor(() => expect(reads).toBe(2));
    expect(result.current.data?.zones[1]?.label).toBe("Zone B");
    expect(result.current.fresh).toBe(false);
    finishReentry!(snapshot());
    await waitFor(() => expect(result.current.fresh).toBe(true));
    rerender({ ...props, admitted: false, actorScope: "9:8:7" });
    expect(result.current.data).toBeNull();
    expect(result.current.fresh).toBe(false);
  });

  it("changed driver invalidates prior signed pair immediately and refetches, with no cache fallback on denied", async () => {
    const requests: string[] = [];
    const fetch = (async (path: string) => {
      requests.push(path);
      if (path.includes("selected_driver_id=11"))
        throw Object.assign(new Error("403 DENIED"), { status: 403 });
      return snapshot();
    }) as ReturnType<typeof useAuthFetch>;
    const props = { fetch, actorScope: "company:principal", admitted: true,
      driverId: "10", vehicleId: "20", routeEvidence: "revision-1" };
    const { result, rerender } = renderHook(p => useLaunchResourceAvailability(p), {
      initialProps: props,
    });
    await waitFor(() => expect(result.current.fresh).toBe(true));
    rerender({ ...props, driverId: "11" });
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(requests).toHaveLength(2));
    await waitFor(() => expect(result.current.error ?? "").toContain("403 DENIED"),
      { timeout: 1500, onTimeout: e => new Error(e.message + JSON.stringify({
        requests, current: result.current,
      })) });
    expect(result.current.fresh).toBe(false);
    expect(requests).toEqual([
      "/dispatch/launch/resource-availability?selected_driver_id=10&selected_vehicle_id=20",
      "/dispatch/launch/resource-availability?selected_driver_id=11&selected_vehicle_id=20",
    ]);
    rerender({ ...props, admitted: false });
    expect(result.current.data).toBeNull();
  });
});