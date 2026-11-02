import { act, renderHook, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  translate: (key: string) => key,
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("./transfers/i18n", () => ({
  useTransferTranslation: () => ({ t: mocks.translate }),
}));
vi.mock("./transfers/parsers", () => ({
  parseTransferPage: (raw: unknown) => raw,
  parseTransferDetail: (raw: unknown) => raw,
}));
vi.mock("./ledger/contracts", () => ({
  parseLedgerPage: (raw: unknown) => raw,
}));
vi.mock("./stocktake/copy", () => ({
  useStocktakeCopy: () => ({ copy: { generic: { sessionsFailed: "Load failed" } } }),
}));
vi.mock("./stocktake/parsers", () => ({
  parseStocktakeSessionPage: (raw: unknown) => raw,
  getErrorMessage: () => "Load failed",
}));

import { useLedgerQuery } from "./ledger/useLedgerQuery";
import { useTransferList } from "./transfers/hooks/useTransferList";
import { useStocktakeSessions } from "./stocktake/hooks/useStocktakeSessions";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
};

beforeEach(() => mocks.fetch.mockReset());

describe("IT-03 V1 admitted tab reentry", () => {
  it("revalidates Ledger on return without dropping same-query rows or reading while hidden", async () => {
    const next = deferred<unknown>();
    mocks.fetch.mockResolvedValueOnce({
      items: [{ id: 41 }], next_cursor: null, has_more: false,
      total: 1, available_types: [],
    }).mockImplementationOnce(() => next.promise);
    const hook = renderHook(({ active }) => useLedgerQuery(11, 0, active), {
      initialProps: { active: true },
    });
    await waitFor(() => expect(hook.result.current.entries).toHaveLength(1));
    await act(async () => hook.rerender({ active: false }));
    const calls = mocks.fetch.mock.calls.length;
    await act(async () => Promise.resolve());
    expect(mocks.fetch).toHaveBeenCalledTimes(calls);
    await act(async () => hook.rerender({ active: true }));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(calls + 1));
    expect(hook.result.current.entries).toHaveLength(1);
    expect(hook.result.current.loading).toBe(true);
    await act(async () => next.resolve({
      items: [{ id: 42 }], next_cursor: null, has_more: false,
      total: 1, available_types: [],
    }));
    await waitFor(() => expect(hook.result.current.entries[0].id).toBe(42));
    hook.unmount();
  });

  it("keeps Stocktake session rows while paused and refreshes on same-location reentry", async () => {
    const next = deferred<unknown>();
    mocks.fetch.mockResolvedValueOnce({
      items: [{ id: 41 }], next_cursor: null, total: 1,
    }).mockImplementationOnce(() => next.promise);
    const hook = renderHook(({ enabled }) => useStocktakeSessions({
      enabled, locationId: 11, authenticatedFetch: mocks.fetch,
    }), { initialProps: { enabled: true } });
    await waitFor(() => expect(hook.result.current.sessions).toHaveLength(1));
    await act(async () => hook.rerender({ enabled: false }));
    const calls = mocks.fetch.mock.calls.length;
    expect(hook.result.current.sessions).toHaveLength(1);
    await act(async () => hook.rerender({ enabled: true }));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(calls + 1));
    expect(hook.result.current.sessions).toHaveLength(1);
    await act(async () => next.resolve({
      items: [{ id: 42 }], next_cursor: null, total: 1,
    }));
    await waitFor(() => expect(hook.result.current.sessions[0].id).toBe(42));
    hook.unmount();
  });

  it("retains a Transfers list while revalidating, and clears it on revoked 403", async () => {
    const next = deferred<unknown>();
    mocks.fetch.mockResolvedValueOnce({
      items: [{ id: 41, status: "PENDING" }], next_cursor: null, total: 1,
    }).mockImplementationOnce(() => next.promise);
    const hook = renderHook(({ active }) => useTransferList(active), {
      initialProps: { active: true },
    });
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    await act(async () => hook.rerender({ active: false }));
    const calls = mocks.fetch.mock.calls.length;
    expect(hook.result.current.items).toHaveLength(1);
    await act(async () => hook.rerender({ active: true }));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(calls + 1));
    expect(hook.result.current.items).toHaveLength(1);
    expect(hook.result.current.loading).toBe(true);
    await act(async () => next.resolve({
      items: [{ id: 42, status: "PENDING" }], next_cursor: null, total: 1,
    }));
    await waitFor(() => expect(hook.result.current.items[0].id).toBe(42));
    mocks.fetch.mockRejectedValueOnce(Object.assign(new Error("Denied"), { status: 403 }));
    act(() => hook.result.current.refreshTransfers());
    await waitFor(() => expect(hook.result.current.failure).not.toBeNull());
    expect(hook.result.current.items).toEqual([]);
    hook.unmount();
  });

  it("retains exactly five scoped panels, with no global keep-all-tabs cache", () => {
    const shell = readFileSync(resolve(process.cwd(), "src/pages/inventory/MainInventory.tsx"), "utf8");
    for (const tab of ["inbound", "stocktake", "ledger", "transfers", "warehouses"]) {
      expect(shell).toContain(`retainTab("${tab}",`);
      expect(shell).toContain(`data-it03-retained-tab="${tab}"`);
      expect(shell).toContain(`active={activeTab === "${tab}"}`);
    }
    expect(shell).toContain("locationAccessVerified");
    expect(shell).toContain("globalAccessVerified");
    expect(shell).toContain("visitedTabScopes[tab] === scope");
    const inbound = readFileSync(resolve(process.cwd(), "src/pages/inventory/Tab2Inbound.tsx"), "utf8");
    expect(inbound).toContain("if (!active || !visibleOptionIds.length) return;");
    expect(inbound).toContain("if (!active) return;");
  });
});
