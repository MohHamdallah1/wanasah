import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import DashboardLayout from "@/components/operations/DashboardLayout";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import {
  beginDashboardSession,
  captureDashboardSession,
  notifyDashboardSessionChange,
} from "@/lib/authStorage";
import { TabTransfers } from "@/pages/inventory/TabTransfers";

const fake = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/components/operations/OperationsSidebar", () => ({ OperationsSidebar: () => null }));
vi.mock("@/hooks/useNetworkStatus", () => ({ useNetworkStatus: () => true }));
vi.mock("sonner", () => ({ toast: {
  error: vi.fn(), success: vi.fn(), warning: vi.fn(), dismiss: vi.fn(),
} }));

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
};

const install = (
  company = "1",
  principal = "11",
  marker = "a",
  event: "local" | "storage" | "none" = "local",
) => {
  beginDashboardSession();
  localStorage.setItem("admin_token", marker + "-access");
  localStorage.setItem("refresh_token", marker + "-refresh");
  localStorage.setItem("company_id", company);
  localStorage.setItem("principal_id", principal);
  localStorage.setItem("backoffice_user_id", principal + "0");
  if (event === "local") notifyDashboardSessionChange();
  if (event === "storage") {
    window.dispatchEvent(new StorageEvent("storage", {
      key: "wanasah:auth-session:generation",
      newValue: localStorage.getItem("wanasah:auth-session:generation"),
    }));
  }
};

const access = (
  companyId: number,
  principalId: number,
  permissions = ["transfer.read", "transfer.send", "transfer.destination"],
) => ({
  company_id: companyId,
  principal_id: principalId,
  backoffice_user_id: principalId * 10,
  is_company_owner: true,
  location_id: null,
  permissions: [],
  any_permissions: permissions,
  location_permissions: [],
});

const identity = (companyId: number) => ({
  company_id: companyId,
  company_name: companyId === 1 ? "Company A" : "Company B",
  company_code: companyId === 1 ? "A" : "B",
  currency_code: "JOD",
  timezone: "Asia/Amman",
  country_id: null,
  country_name: null,
  display_location: companyId === 1 ? "A Location" : "B Location",
});

const transfer = (companyId: number) => {
  const a = companyId === 1;
  return {
    id: a ? 1001 : 2001,
    reference_number: a ? "A-TRANSFER" : "B-TRANSFER",
    source_location_id: a ? 101 : 201,
    source_location_name: a ? "A Source" : "B Source",
    destination_location_id: a ? 102 : 202,
    destination_location_name: a ? "A Destination" : "B Destination",
    status: "IN_TRANSIT",
    transfer_purpose: "WAREHOUSE_BALANCING",
    dispatched_by: a ? 110 : 220,
    dispatched_by_name: a ? "A Operator" : "B Operator",
    received_by: null,
    received_by_name: null,
    cancelled_by: null,
    cancelled_by_name: null,
    line_count: 1,
    total_quantity: "8",
    notes: null,
    decision_reason: null,
    created_at: "2026-10-31T00:00:00Z",
    updated_at: "2026-10-31T00:00:00Z",
    accepted_at: null,
    rejected_at: null,
    cancelled_at: null,
    posted_at: null,
  };
};

const wrapperFor = (client: QueryClient) =>
  ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );

beforeEach(() => {
  localStorage.clear();
  fake.fetch.mockReset();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

it("drops A Transfers before a fresh B authorization/read and preserves durable drafts", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const freshBAccess = deferred<void>();
  const freshBList = deferred<void>();
  const freshBListStarted = deferred<void>();
  const lateAList = deferred<void>();
  const lateAListStarted = deferred<void>();
  let holdFreshB = false;
  let aListReads = 0;

  fake.fetch.mockImplementation(async (path: string) => {
    const company = Number(localStorage.getItem("company_id"));
    const principal = Number(localStorage.getItem("principal_id"));

    if (path.startsWith("/inventory/access/me")) {
      if (company === 2 && holdFreshB) await freshBAccess.promise;
      return access(company, principal);
    }
    if (path === "/tenant/identity") return identity(company);
    if (path === "/inventory/access/locations/capabilities") {
      const ids = company === 1 ? [101, 102] : [201, 202];
      return { locations: {
        [ids[0]]: ["transfer.cancel"],
        [ids[1]]: ["transfer.receive", "transfer.reject"],
      } };
    }
    if (path.startsWith("/warehouse/unified/transfers?")) {
      if (company === 1) {
        aListReads += 1;
        if (aListReads > 1) {
          lateAListStarted.resolve();
          await lateAList.promise;
          return {
            items: [{ ...transfer(1), source_location_name: "A LATE SECRET" }],
            next_cursor: null, has_more: false, total: 1,
          };
        }
        return { items: [transfer(1)], next_cursor: null, has_more: false, total: 1 };
      }
      freshBListStarted.resolve();
      await freshBList.promise;
      return { items: [transfer(2)], next_cursor: null, has_more: false, total: 1 };
    }
    throw new Error("Unexpected platform-boundary request: " + path);
  });

  install("2", "22", "warm-b");
  const warm = renderHook(() => useInventoryAccess(), { wrapper: wrapperFor(client) });
  await waitFor(() => expect(warm.result.current.data?.company_id).toBe(2));
  const cachedBGeneration = captureDashboardSession().generation;
  warm.unmount();

  install("1", "11", "a");
  const durableKey = "wanasah:durable:v1:1:11:dispatch-adjust-base:9";
  const durableValue = JSON.stringify({ requestId: "keep-me", payload: { delta_base: "-5" } });
  localStorage.setItem(durableKey, durableValue);

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/session-boundary-transfers"]}>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route path="/session-boundary-transfers" element={<TabTransfers onInventoryChanged={() => undefined} />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await waitFor(() => expect(screen.queryAllByText("A Source").length).toBeGreaterThan(0));
  await waitFor(() => {
    const receive = document.querySelector<HTMLButtonElement>('[data-cp13-transfer-decision="receive"]');
    expect(receive).not.toBeNull();
    expect(receive?.disabled).toBe(false);
  });
  const oldAction = document.querySelector<HTMLButtonElement>('[data-cp13-transfer-decision="receive"]')!;
  fireEvent.click(oldAction);
  const oldDialog = screen.getByRole("dialog");

  const refresh = document.querySelector<HTMLButtonElement>(
    '[data-cp13-controls="transfer-list"] button[title]',
  );
  expect(refresh).not.toBeNull();
  fireEvent.click(refresh!);
  await lateAListStarted.promise;

  holdFreshB = true;
  act(() => install("2", "22", "b", "storage"));
  expect(captureDashboardSession().generation).not.toBe(cachedBGeneration);
  expect(screen.queryAllByText("A Source")).toHaveLength(0);
  expect(screen.queryAllByText("A Destination")).toHaveLength(0);
  expect(oldAction).not.toBeInTheDocument();
  expect(oldDialog).not.toBeInTheDocument();
  expect(screen.queryAllByText("B Source")).toHaveLength(0);
  expect(localStorage.getItem(durableKey)).toBe(durableValue);

  await act(async () => freshBAccess.resolve());
  await freshBListStarted.promise;
  expect(screen.queryAllByText("A Source")).toHaveLength(0);
  expect(screen.queryAllByText("B Source")).toHaveLength(0);

  await act(async () => lateAList.resolve());
  expect(document.body.textContent).not.toContain("A LATE SECRET");

  await act(async () => freshBList.resolve());
  await waitFor(() => expect(screen.queryAllByText("B Source").length).toBeGreaterThan(0));
  expect(screen.queryAllByText("A Source")).toHaveLength(0);
  expect(document.body.textContent).not.toContain("A LATE SECRET");
  expect(localStorage.getItem(durableKey)).toBe(durableValue);
  client.clear();
});

it("same-principal re-login generation never reuses cached inventory authorization", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const secondAccess = deferred<void>();
  let reads = 0;

  fake.fetch.mockImplementation(async (path: string) => {
    if (!path.startsWith("/inventory/access/me")) {
      throw new Error("Unexpected access request: " + path);
    }
    reads += 1;
    if (reads === 1) return access(1, 11, ["transfer.read"]);
    await secondAccess.promise;
    return access(1, 11, []);
  });

  install("1", "11", "first");
  const view = renderHook(() => useInventoryAccess(), { wrapper: wrapperFor(client) });
  await waitFor(() => expect(view.result.current.canAny("transfer.read")).toBe(true));

  act(() => install("1", "11", "second"));
  expect(view.result.current.data).toBeUndefined();
  expect(view.result.current.canAny("transfer.read")).toBe(false);
  await waitFor(() => expect(reads).toBe(2));

  await act(async () => secondAccess.resolve());
  await waitFor(() => expect(view.result.current.data?.company_id).toBe(1));
  expect(view.result.current.canAny("transfer.read")).toBe(false);
  client.clear();
});
