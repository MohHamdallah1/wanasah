import { webcrypto } from "node:crypto";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Shortage } from "@/types/dispatch";
import type { DashboardSession } from "@/lib/authStorage";
import { clearLocalStoragePreservingLoginHintsAndPreferences } from "@/lib/authStorage";
import { readDurableCommand } from "@/lib/durableOperations";
import { setAppLanguage } from "@/i18n";
import {
  buildGroupIntent, groupMutationBody, groupText, isGroupIntent,
  parseGroupResponse, shortageGroupScope, verifiedGroupReadback,
  type GroupIntent, type GroupLine,
} from "@/features/dispatch/shortageGroup/contract";
import { useShortageGroupCommit } from "@/features/dispatch/shortageGroup/useShortageGroupCommit";
import { ShortageModal } from "@/components/dispatch/ShortageModal";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const access = vi.hoisted(() => ({ current: true }));
vi.mock("sonner", () => ({ toast }));
vi.mock("@/lib/authStorage", async orig => ({
  ...await orig<typeof import("@/lib/authStorage")>(),
  isDashboardSessionCurrent: () => access.current,
}));
vi.mock("@/components/dispatch/ShortageProductPicker", () => ({
  ShortageProductPicker: () => <div data-testid="shortage-product-picker"/>,
}));

const heldLocks = new Set<string>();
const fakeLocks = {
  request: async <T,>(name: string, _opts: unknown, callback: (lock: object | null) => Promise<T>): Promise<T> => {
    if (heldLocks.has(name)) return callback(null);
    heldLocks.add(name);
    try { return await callback({ name }); }
    finally { heldLocks.delete(name); }
  },
};

const session = { generation: "generation-1", identity: "company:1:principal:11" } as DashboardSession;
const initial: Shortage[] = [
  {
    id: "10", productId: "41", zoneId: "3", zoneName: "Area", shopId: "7",
    shopName: "Shop", driverId: "9", driverName: "Driver", productName: "Chips",
    quantity: 4, status: "pending",
  },
  {
    id: "11", productId: "42", zoneId: "3", zoneName: "Area", shopId: "7",
    shopName: "Shop", driverId: "9", driverName: "Driver", productName: "Snack",
    quantity: 2, status: "pending",
  },
];
const lines: GroupLine[] = [
  { zoneId: 3, shopId: 7, driverId: 9, productId: 41, quantity: 8 },
  { zoneId: 3, shopId: 7, driverId: 9, productId: 42, quantity: 5 },
];
const draft = [
  { productId: "41", productName: "Chips", quantity: 8 },
  { productId: "42", productName: "Snack", quantity: 5 },
];
const ids = ["10", "11"];
const httpError = (status: number, code: string) =>
  Object.assign(new Error("private transport diagnostic"), {
    status, code, data: { error: { code } },
  });

function fakeServer(action: "edit" | "delete" = "edit") {
  let rows = [...initial];
  let commits = 0;
  let lost = false;
  let failReadback = false;
  let offlinePreflight = false;
  let failPut: number | null = null;
  const records = new Map<string, { body: string; response: unknown }>();
  const bodies: string[] = [];
  let gets = 0;
  const fetch = vi.fn().mockImplementation(async (url: string, options?: RequestInit): Promise<unknown> => {
    if (url === "/dispatch/shortages" && options?.method !== "PUT") {
      gets++;
      if (offlinePreflight) {
        offlinePreflight = false;
        throw new Error("network offline before any PUT");
      }
      if (failReadback && commits > 0) {
        failReadback = false;
        throw new Error("lost authorized GET");
      }
      return [...rows];
    }
    expect(url).toBe("/dispatch/shortages/group");
    expect(options?.method).toBe("PUT");
    const body = String(options?.body);
    const request = JSON.parse(body) as {
      request_id: string;
      shortage_ids: number[];
      items: GroupLine[];
    };
    bodies.push(body);
    if (failPut !== null) throw httpError(failPut, "SERVER_REJECTION");
    const old = records.get(request.request_id);
    if (old) {
      expect(body).toBe(old.body);
      return old.response;
    }
    expect(request.shortage_ids).toEqual([10, 11]);
    commits++;
    rows = rows.filter(x => !request.shortage_ids.includes(Number(x.id)));
    const newIds = action === "edit" ? [100 + commits * 2, 101 + commits * 2] : [];
    if (action === "edit") {
      rows = [...rows, ...request.items.map((x, index) => ({
        ...initial[index], id: String(newIds[index]),
        productId: String(x.productId), zoneId: String(x.zoneId),
        shopId: String(x.shopId), driverId: String(x.driverId),
        quantity: x.quantity,
      }))];
    }
    const response = {
      message: "ok", request_id: request.request_id, shortage_ids: newIds,
    };
    records.set(request.request_id, { body, response });
    if (lost) {
      lost = false;
      throw new Error("POSTCOMMIT_RESPONSE_LOST");
    }
    return response;
  });
  return {
    fetch, bodies, getRows: () => rows, getCommits: () => commits,
    getGets: () => gets, setLost: () => { lost = true; },
    setReadbackFailure: () => { failReadback = true; },
    setOfflinePreflight: () => { offlinePreflight = true; },
    setPutError: (status: number | null) => { failPut = status; },
  };
}
const args = (fetch: (url: string, options?: RequestInit) => Promise<unknown>, language = "en") => ({
  session, authorized: true, language, fetch, onVerified: vi.fn(), onRestored: vi.fn(),
});
const ready = async (hook: { result: { current: { restoring: boolean } } }) =>
  waitFor(() => expect(hook.result.current.restoring).toBe(false));

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "11");
  localStorage.setItem("backoffice_user_id", "110");
  vi.stubGlobal("crypto", webcrypto);
  Object.defineProperty(navigator, "locks", { configurable: true, value: fakeLocks });
  heldLocks.clear();
  access.current = true;
  toast.success.mockReset(); toast.error.mockReset(); toast.info.mockReset();
  await setAppLanguage("ar");
});
afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
});

describe("D05 canonical grouped-shortage original operation identity", () => {
  it("validates immutable original IDs and exact backend field shape, never sends presentation fields", () => {
    const intent = buildGroupIntent(ids, lines, draft);
    expect(intent.shortageIds).toEqual([10, 11]);
    const requestId = "ded0c901-babc-4455-9abc-000000000003";
    expect(groupMutationBody(requestId, intent)).toEqual({
      request_id: requestId, shortage_ids: [10, 11], items: lines,
    });
    expect(JSON.stringify(groupMutationBody(requestId, intent))).not.toContain("productName");
    expect(() => buildGroupIntent(["10", "10"], [], [])).toThrow();
    expect(() => buildGroupIntent(["0"], [], [])).toThrow();
    expect(() => buildGroupIntent(ids, [
      lines[0], { ...lines[0] },
    ], draft)).toThrow();
    expect(isGroupIntent({ ...intent, action: "delete" })).toBe(false);
    const receipt = parseGroupResponse({ request_id: requestId, shortage_ids: [102, 103] }, requestId)!;
    expect(verifiedGroupReadback(
      lines.map((x, i) => ({ ...initial[i], id: String(102 + i), productId: String(x.productId),
        quantity: x.quantity })), intent, receipt,
    )).toBe(true);
    expect(verifiedGroupReadback(initial, intent, receipt)).toBe(false);
    expect(parseGroupResponse({ request_id: crypto.randomUUID(), shortage_ids: [102, 103] }, requestId)).toBeNull();
  });

  it.each(["ar", "en"] as const)(
    "lost committed edit PUT -> re-login -> EXACT same UUID and full body replay -> canonical GET, %s",
    async language => {
      await setAppLanguage(language);
      const backend = fakeServer("edit");
      backend.setLost();
      const firstProps = args(backend.fetch, language);
      const first = renderHook(() => useShortageGroupCommit(firstProps));
      await ready(first);
      await act(async () => { expect(await first.result.current.save(ids, lines, draft)).toBe(false); });
      expect(first.result.current.hasUnresolved).toBe(true);
      expect(firstProps.onVerified).not.toHaveBeenCalled();
      expect(toast.success).not.toHaveBeenCalled();
      const persisted = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
      expect(persisted?.payload).toMatchObject({ action: "edit", shortageIds: [10, 11], items: lines, draft });
      const originalId = persisted!.requestId;
      expect(backend.getCommits()).toBe(1);
      first.unmount();

      expect(clearLocalStoragePreservingLoginHintsAndPreferences()).toBe(true);
      localStorage.setItem("company_id", "1"); localStorage.setItem("principal_id", "11");
      const nextProps = args(backend.fetch, language);
      const second = renderHook(() => useShortageGroupCommit(nextProps));
      await waitFor(() => expect(second.result.current.pending?.requestId).toBe(originalId));
      expect(nextProps.onRestored).toHaveBeenCalledWith(expect.objectContaining({ action: "edit" }));
      await act(async () => { expect(await second.result.current.retry()).toBe(true); });
      expect(backend.getCommits()).toBe(1);
      expect(backend.bodies).toHaveLength(2);
      expect(backend.bodies[1]).toBe(backend.bodies[0]);
      expect(JSON.parse(backend.bodies[1]).request_id).toBe(originalId);
      expect(await readDurableCommand(shortageGroupScope()!)).toBeNull();
      expect(toast.success).toHaveBeenCalledOnce();
      expect(nextProps.onVerified).toHaveBeenCalledOnce();
      second.unmount();
    },
  );

  it("Delete All: 200 commit then dropped GET retains original key and replays only deletion", async () => {
    const backend = fakeServer("delete");
    backend.setReadbackFailure();
    const props = args(backend.fetch);
    const hooked = renderHook(() => useShortageGroupCommit(props));
    await ready(hooked);
    await act(async () => { expect(await hooked.result.current.save(ids, [], [])).toBe(false); });
    const original = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
    expect(original?.payload.items).toEqual([]);
    expect(original?.payload.action).toBe("delete");
    expect(backend.getRows()).toEqual([]);
    expect(backend.getCommits()).toBe(1);
    expect(props.onVerified).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    await act(async () => { expect(await hooked.result.current.retry()).toBe(true); });
    expect(backend.getCommits()).toBe(1);
    expect(backend.bodies).toHaveLength(2);
    expect(backend.bodies[0]).toBe(backend.bodies[1]);
    expect(toast.success).toHaveBeenCalledOnce();
    expect(await readDurableCommand(shortageGroupScope()!)).toBeNull();
  });

  it("failed GET preflight is definitively UNSENT: no pending command or PUT, retry may create new intent", async () => {
    const backend = fakeServer();
    backend.setOfflinePreflight();
    const hooked = renderHook(() => useShortageGroupCommit(args(backend.fetch)));
    await ready(hooked);
    await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(false); });
    expect(backend.bodies).toHaveLength(0);
    expect(await readDurableCommand(shortageGroupScope()!)).toBeNull();
    await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(true); });
    expect(backend.getCommits()).toBe(1);
    expect(backend.bodies).toHaveLength(1);
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it("stale selected IDs before first send block PUT and do not create operation identity", async () => {
    const fetch = vi.fn().mockResolvedValue([]);
    const hooked = renderHook(() => useShortageGroupCommit(args(fetch)));
    await ready(hooked);
    await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(false); });
    expect(fetch.mock.calls.filter(([, opt]) => opt?.method === "PUT")).toHaveLength(0);
    expect(await readDurableCommand(shortageGroupScope()!)).toBeNull();
  });

  it("changed intended payload during uncertainty NEVER replaces the old saved request ID", async () => {
    const backend = fakeServer();
    backend.setLost();
    const hooked = renderHook(() => useShortageGroupCommit(args(backend.fetch)));
    await ready(hooked);
    await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(false); });
    const first = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
    await act(async () => {
      expect(await hooked.result.current.save(ids, [{ ...lines[0], quantity: 999 }], [
        { ...draft[0], quantity: 999 },
      ])).toBe(false);
    });
    const next = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
    expect(next?.requestId).toBe(first?.requestId);
    expect(next?.payload).toEqual(first?.payload);
    expect(backend.bodies).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it.each([401, 403, 409, 500])(
    "HTTP %i on exact replay retains the original command and never claims success",
    async status => {
      const backend = fakeServer();
      backend.setLost();
      const hooked = renderHook(() => useShortageGroupCommit(args(backend.fetch)));
      await ready(hooked);
      await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(false); });
      const original = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
      backend.setPutError(status);
      await act(async () => { expect(await hooked.result.current.retry()).toBe(false); });
      const saved = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
      expect(saved?.requestId).toBe(original?.requestId);
      expect(saved?.payload).toEqual(original?.payload);
      expect(toast.success).not.toHaveBeenCalled();
    },
  );

  it("a real definitive 404 on original request is not misreported as success", async () => {
    const backend = fakeServer();
    backend.setPutError(404);
    const hooked = renderHook(() => useShortageGroupCommit(args(backend.fetch)));
    await ready(hooked);
    await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(false); });
    expect(toast.success).not.toHaveBeenCalled();
    expect(await readDurableCommand(shortageGroupScope()!)).toBeNull();
    expect(hooked.result.current.hasUnresolved).toBe(false);
  });

  it("cross-company and principal switches never restore or mutate earlier scope", async () => {
    const backend = fakeServer();
    backend.setLost();
    const old = renderHook(() => useShortageGroupCommit(args(backend.fetch)));
    await ready(old);
    await act(async () => { expect(await old.result.current.save(ids, lines, draft)).toBe(false); });
    const scope = shortageGroupScope()!;
    const original = await readDurableCommand(scope);
    old.unmount();
    localStorage.setItem("company_id", "2");
    localStorage.setItem("principal_id", "22");
    const newer = renderHook(() => useShortageGroupCommit(args(vi.fn().mockResolvedValue([]))));
    await ready(newer);
    expect(newer.result.current.hasUnresolved).toBe(false);
    await act(async () => { expect(await newer.result.current.retry()).toBe(false); });
    expect(await readDurableCommand(scope)).toEqual(original);
    expect(toast.success).not.toHaveBeenCalled();
    newer.unmount();
  });

  it("corrupt durable storage and missing principal both block ANY mutation without removing old data", async () => {
    const scope = shortageGroupScope()!;
    localStorage.setItem(scope, "not-json");
    const fetch = vi.fn().mockResolvedValue(initial);
    const corrupt = renderHook(() => useShortageGroupCommit(args(fetch)));
    await ready(corrupt);
    expect(corrupt.result.current.blocked).toBe(true);
    await act(async () => { expect(await corrupt.result.current.save(ids, lines, draft)).toBe(false); });
    expect(fetch).not.toHaveBeenCalled();
    corrupt.unmount();

    localStorage.removeItem("principal_id");
    const missing = renderHook(() => useShortageGroupCommit(args(fetch)));
    await ready(missing);
    expect(missing.result.current.blocked).toBe(true);
    await act(async () => { expect(await missing.result.current.save(ids, [], [])).toBe(false); });
    expect(fetch).not.toHaveBeenCalled();
    missing.unmount();
  });

  it("simultaneous empty-scope tab claims serialize before durable read/write and PUT", async () => {
    let release!: (value: unknown) => void;
    const delayed = new Promise<unknown>(yes => { release = yes; });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "PUT" ? delayed : initial,
    );
    const first = renderHook(() => useShortageGroupCommit(args(fetch)));
    const second = renderHook(() => useShortageGroupCommit(args(fetch)));
    await ready(first); await ready(second);
    let one!: Promise<boolean>; let two!: Promise<boolean>;
    act(() => {
      one = first.result.current.save(ids, lines, draft);
      two = second.result.current.save(ids, [{ ...lines[0], quantity: 99 }], [
        { ...draft[0], quantity: 99 },
      ]);
    });
    await act(async () => { expect(await two).toBe(false); });
    await waitFor(() => expect(fetch.mock.calls.filter(([, opt]) => opt?.method === "PUT")).toHaveLength(1));
    const saved = await readDurableCommand<GroupIntent>(shortageGroupScope()!);
    expect(saved?.payload.items).toEqual(lines);
    await act(async () => { release({ request_id: saved!.requestId, shortage_ids: [102, 103] }); expect(await one).toBe(false); });
    expect(fetch.mock.calls.filter(([, opt]) => opt?.method === "PUT")).toHaveLength(1);
    expect(heldLocks.size).toBe(0);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("stale old session callback after logout cannot toast, clear, or reconcile new principal", async () => {
    let release!: (response: unknown) => void;
    const stalled = new Promise<unknown>(yes => { release = yes; });
    const fetch = vi.fn().mockImplementation(async (_path: string, opt?: RequestInit) =>
      opt?.method === "PUT" ? stalled : initial,
    );
    const oldProps = args(fetch);
    const old = renderHook(() => useShortageGroupCommit(oldProps));
    await ready(old);
    let operation!: Promise<boolean>;
    act(() => { operation = old.result.current.save(ids, lines, draft); });
    await waitFor(() => expect(fetch.mock.calls.some(([, o]) => o?.method === "PUT")).toBe(true));
    const key = shortageGroupScope()!;
    const record = await readDurableCommand<GroupIntent>(key);
    old.unmount();
    access.current = false;
    localStorage.setItem("company_id", "2");
    localStorage.setItem("principal_id", "22");
    await act(async () => {
      release({ request_id: record!.requestId, shortage_ids: [102, 103] });
      expect(await operation).toBe(false);
    });
    expect(await readDurableCommand(key)).toEqual(record);
    expect(toast.success).not.toHaveBeenCalled();
    expect(oldProps.onVerified).not.toHaveBeenCalled();
  });

  it("browsers without cross-tab Web Locks reject mutation before any GET or PUT", async () => {
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    const fetch = vi.fn().mockResolvedValue(initial);
    const hooked = renderHook(() => useShortageGroupCommit(args(fetch)));
    await ready(hooked);
    await act(async () => { expect(await hooked.result.current.save(ids, lines, draft)).toBe(false); });
    expect(fetch).not.toHaveBeenCalled();
    expect(await readDurableCommand(shortageGroupScope()!)).toBeNull();
  });
});

describe("D05 shortage grouped operation recovery AR/EN responsive UI", () => {
  it.each(["ar", "en"] as const)("shows one accessible explicit same-key retry at 390/700/1440 in %s", async language => {
    await setAppLanguage(language);
    for (const width of [390, 700, 1440]) {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
      const onRetry = vi.fn();
      const intent = buildGroupIntent(ids, lines, draft);
      const view = render(
        <ShortageModal isOpen onClose={vi.fn()} zones={[]} activeShops={[]}
          shortageZoneId="3" shortageShopId="7" onZoneChange={vi.fn()} onShopChange={vi.fn()}
          productScope="1:11" newShortage={{ quantity: 1 }} onNewShortageChange={vi.fn()}
          shortageDraft={draft} onAddProductToDraft={vi.fn()} onRemoveProductFromDraft={vi.fn()}
          onUpdateDraftQty={vi.fn()} onClearDraft={vi.fn()}
          onConfirmShortages={vi.fn()} shortages={initial} onDeleteShortage={vi.fn()}
          onDeleteShortageGroup={vi.fn()} onEditShortageGroup={vi.fn()}
          editingShortageIds={ids} onCancelEdit={vi.fn()}
          drivers={[]} shortageDriverId="9" onDriverChange={vi.fn()}
          groupRecovery={{
            pending: { requestId: "ded0c901-babc-4455-9abc-000000000003", payload: intent },
            blocked: false, restoring: false, busy: false, feedback: groupText(language, "unknown"),
            onRetry,
          }}
        />,
      );
      expect(screen.getByTestId("shortage-group-recovery")).toBeInTheDocument();
      expect(screen.getByText(groupText(language, "pending"))).toBeInTheDocument();
      expect(screen.getByText(/ded0c901-babc-4455-9abc-000000000003/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: groupText(language, "retry") }));
      expect(onRetry).toHaveBeenCalledOnce();
      expect(screen.getByText(/Chips/)).toBeInTheDocument();
      view.unmount();
    }
  });
});
