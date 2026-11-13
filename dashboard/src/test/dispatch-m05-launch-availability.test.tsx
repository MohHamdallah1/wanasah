import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { LaunchResourceSelect } from "@/features/dispatch/launchResources/LaunchResourceSelect";
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
    { id: "101", label: "Zone B", available: true, code: "AVAILABLE" as const }],
  drivers: [{ id: "10", label: "Ahmed", available: true, code: "AVAILABLE" as const },
    { id: "11", label: "Ali", available: false, code: "REPRESENTATIVE_ON_ROUTE" as const }],
  vehicles: [{ id: "20", label: "Vehicle A", available: true, code: "AVAILABLE" as const },
    { id: "21", label: "Vehicle B", available: false, code: "VEHICLE_ON_ROUTE" as const }],
  warehouses: [{ id: "30", label: "WH", available: true, code: "AVAILABLE" as const }],
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

  it("renders one RTL dropdown grouped available first, then truly disabled/unselectable busy drivers", () => {
    const change = vi.fn();
    render(<LaunchResourceSelect label="المندوب" kind="drivers" options={snapshot().drivers}
      value="" onChange={change} disabled={false} placeholder="اختر المندوب"/>);
    expect(screen.getByTestId("m05-launch-drivers")).toHaveAttribute("dir", "rtl");
    fireEvent.click(screen.getByRole("button", { name: "اختر المندوب" }));
    expect(screen.getByText("المتاح (1)")).toBeVisible();
    expect(screen.getByText("غير المتاح (1)")).toBeVisible();
    const buttons = screen.getAllByRole("button");
    expect(buttons.find(x => x.textContent === "Ahmed")?.compareDocumentPosition(
      buttons.find(x => x.textContent?.includes("Ali"))!,
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const busy = screen.getByRole("button", { name: "Ali" });
    expect(busy).toBeDisabled();
    expect(busy).toHaveTextContent("المندوب مرتبط بخط نشط");
    fireEvent.click(busy);
    expect(change).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Ahmed" }));
    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith("10");
  });

  it("English LTR vehicle unavailable reason remains visible, not hidden or selectable", () => {
    language.current = "en";
    const change = vi.fn();
    render(<LaunchResourceSelect label="Vehicle" kind="vehicles" options={snapshot().vehicles}
      value="21" onChange={change} disabled={false} placeholder="Select vehicle"/>);
    const root = screen.getByTestId("m05-launch-vehicles");
    expect(root).toHaveAttribute("dir", "ltr");
    expect(root).toHaveTextContent("Vehicle assigned to an active or paused route");
    fireEvent.click(screen.getByRole("button", { name: "Vehicle B" }));
    expect(screen.getByText("Unavailable (1)")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Vehicle B" }).some(x => x.hasAttribute("disabled"))).toBe(true);
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
