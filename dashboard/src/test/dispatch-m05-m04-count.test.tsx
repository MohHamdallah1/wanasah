import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {
  submitSignedVehicleCount,
} from "@/features/operations/representativeSettlement/vehicleCountCommand";
import { SignedMultiVehicleCustodyJourney } from "@/features/operations/representativeSettlement/SignedMultiVehicleCustodyJourney";
import type { SettlementAuthFetch } from "@/features/operations/representativeSettlement/api";

vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children, title }: {
    isOpen: boolean; children: ReactNode; title: string;
  }) => isOpen ? <div role="dialog" aria-label={title}>{children}</div> : null,
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ i18n: { language: "ar", resolvedLanguage: "ar", dir: () => "rtl" } }),
}));

const countBody = {
  mode: "COUNT_IN_PLACE" as const, snapshot_token: "a".repeat(64),
  receiver_confirms_count: true as const,
  destination_location_id: null, receiver_confirms_handoff: false,
  items: [{ line_key: "a".repeat(24), actual_quantity: "83" }], notes: null,
};
const list = (second: "NOT_COUNTED" | "COUNT_SIGNED" = "NOT_COUNTED") => ({
  work_session_id: 900, work_session_ended: true, financially_settled: false,
  all_vehicle_counts_signed: second === "COUNT_SIGNED",
  vehicles: [
    { vehicle_id: 4, vehicle_location_id: 40, plate_number: "A",
      period_ids: [11, 13], custody_epoch_ids: [21, 23],
      checkpoint_status: "COUNT_SIGNED", checkpoint_id: 301, checkpoint_mode: "COUNT_IN_PLACE" },
    { vehicle_id: 5, vehicle_location_id: 50, plate_number: "B",
      period_ids: [12], custody_epoch_ids: [22],
      checkpoint_status: second, checkpoint_id: second === "COUNT_SIGNED" ? 302 : null,
      checkpoint_mode: second === "COUNT_SIGNED" ? "COUNT_IN_PLACE" : null },
  ],
});

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("backoffice_user_id", "2");
  vi.stubGlobal("crypto", webcrypto);
  Object.defineProperty(navigator, "locks", {
    configurable: true, value: { request: async (
      _name: string, _opts: unknown, callback: (lock: object) => Promise<unknown>,
    ) => callback({}) },
  });
});
afterEach(() => {
  cleanup(); vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
});
describe("M05 actual merged M04 all-car count integration", () => {
  it("COUNT_IN_PLACE posts signed vehicle B with exact immutable token and zero implied handoff", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    const fetch = (async (path: string, init?: RequestInit) => {
      requests.push({ path, body: JSON.parse(String(init?.body)) });
      return { status: "VEHICLE_CUSTODY_SEALED", mode: "COUNT_IN_PLACE",
        vehicle_id: 5, checkpoint_id: 302, movement_count: 0, financial_ready: false };
    }) as SettlementAuthFetch;
    const result = await submitSignedVehicleCount(fetch, 900, 5, countBody);
    expect(result.movement_count).toBe(0);
    expect(result.financial_ready).toBe(false);
    expect(requests).toHaveLength(1);
    expect(requests[0].path).toBe("/admin/sessions/900/inventory-custody/vehicles/5/count");
    expect(requests[0].body).toMatchObject({
      ...countBody, request_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    });
  });

  it("forbids unsigned PHYSICAL_HANDOFF and changed destination without receiver consent", async () => {
    const fetch = vi.fn() as unknown as SettlementAuthFetch;
    await expect(submitSignedVehicleCount(fetch, 900, 5, {
      ...countBody, mode: "PHYSICAL_HANDOFF", destination_location_id: 77,
      receiver_confirms_handoff: false,
    })).rejects.toThrow("M05_UNCONFIRMED_PHYSICAL_HANDOFF");
    expect(fetch).not.toHaveBeenCalled();
    await expect(submitSignedVehicleCount(fetch, 900, 5, {
      ...countBody, mode: "COUNT_IN_PLACE", destination_location_id: 77,
    })).rejects.toThrow("M05_UNCONFIRMED_PHYSICAL_HANDOFF");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not present all cars signed or financial readiness before B posts", async () => {
    const fetch = vi.fn(async (path: string) => {
      if (path === "/admin/sessions/900/inventory-custody/vehicles") return list();
      if (path === "/warehouse/unified/transfer/locations?limit=100&purpose=destination") {
        return { items: [], next_cursor: null, has_more: false, total: 0 };
      }
      if (path.endsWith("/vehicles/5")) return {
        work_session_id: 900, vehicle_id: 5, vehicle_plate: "B",
        snapshot_token: "b".repeat(64), epoch_count: 1,
        lines: [{ line_key: "b".repeat(24), product_name: "Lolo",
          sku: "LOLO", batch_number: "B1", expiry_date: null,
          stock_status: "AVAILABLE", uom: "EACH", expected_quantity: "53" }],
      };
      throw new Error("Unexpected request " + path);
    }) as unknown as SettlementAuthFetch;
    const onCountsCompleted = vi.fn();
    render(<SignedMultiVehicleCustodyJourney isOpen onClose={vi.fn()}
      driverName="Driver" sessionId={900} authFetch={fetch}
      onCountsCompleted={onCountsCompleted}/>);
    await screen.findByRole("button", { name: "جرد السيارة B" });
    expect(onCountsCompleted).not.toHaveBeenCalled();
    expect(screen.queryByText(/جرد كل السيارات معتمد/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "جرد السيارة B" }));
    await screen.findByText("Lolo · AVAILABLE · B1 · —");
    expect(screen.getByRole("button", { name: "اعتماد جرد هذه السيارة" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("أؤكد الكميات الفعلية لهذه السيارة فقط"));
    await waitFor(() => expect(screen.getByRole("button", { name: "اعتماد جرد هذه السيارة" })).toBeEnabled());
    expect(onCountsCompleted).not.toHaveBeenCalled();
  });

  it("only signed all-car and ended S1 triggers finance-status refresh; never a client financial grant", async () => {
    const fetch = (async (path: string) => {
      if (path === "/admin/sessions/900/inventory-custody/vehicles") return list("COUNT_SIGNED");
      return { items: [], next_cursor: null, has_more: false, total: 0 };
    }) as SettlementAuthFetch;
    const onCountsCompleted = vi.fn();
    render(<SignedMultiVehicleCustodyJourney isOpen onClose={vi.fn()}
      driverName="Driver" sessionId={900} authFetch={fetch}
      onCountsCompleted={onCountsCompleted}/>);
    await waitFor(() => expect(onCountsCompleted).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/يتم التحقق من جاهزية التسوية المالية لدى الخادم/)).toBeVisible();
  });
});
