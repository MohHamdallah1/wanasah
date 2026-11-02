import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  language: "en",
  t: (key: string) => key,
}));
vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));
vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: mocks.t,
    i18n: { language: mocks.language, resolvedLanguage: mocks.language,
      dir: () => mocks.language === "ar" ? "rtl" : "ltr" },
  }),
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ children, isOpen }: { children: ReactNode; isOpen: boolean }) =>
    isOpen ? <div role="dialog" dir={mocks.language === "ar" ? "rtl" : "ltr"}>{children}</div> : null,
}));

import { BatchDetailPanel } from "@/pages/inventory/liveStock/BatchDetailPanel";
import { useLiveStockBatchDetail } from "@/pages/inventory/liveStock/useLiveStockBatchDetail";
import { parseBatchDetailResponse, type WarehouseProduct } from "@/pages/inventory/liveStock/contracts";
import { parseLiveStockWarehouseSource } from "@/pages/inventory/liveStock/sourceContract";

const product = { id: 41, currency_code: "JOD", name: "Product 41",
  sku: "SKU-41", family_name: "Family", display_uom_code: "EA",
  base_uom_code: "EA", display_factor_to_base: "1" } as WarehouseProduct;

const batchRaw = (qty = "2.500001") => ({
  batch_id: 71, batch_number: null, production_date: null, expiry_date: null,
  disposition: "RELEASED", disposition_revision: 1, disposition_reason: null,
  allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"],
  days_to_expiry: null,
  on_hand_quantity: qty, reserved_quantity: "0.500001",
  available_for_sale_quantity: "2", unavailable_quantity: "0",
  restricted_quantity: "0", expiry_unavailable_quantity: "0",
  quarantined_quantity: "0", blocked_quantity: "0", recalled_quantity: "0",
  damaged_quantity: "0", disposal_pending_quantity: "0",
  latest_purchase_cost: null, latest_purchase_uom_code: null,
  latest_purchase_date: null, purchase_event_count: 0,
});
const batchPage = (qty = "2.500001") => ({
  location_id: 11, product_variant_id: 41, currency_code: "JOD",
  batches: [batchRaw(qty)], next_cursor: null, has_more: false,
});
const sourcePayload = (qty = "2.500001", batchId = 71, locationId = 11) => ({
  location_id: locationId, product_variant_id: 41, batch_id: batchId,
  location_name: "Warehouse 11",
  statuses: [{
    stock_status: "AVAILABLE", on_hand_quantity: qty,
    reserved_quantity: "0.500001", movable_quantity: "2",
    reservation_evidence: { coverage: "UNRESOLVED", owners: [],
      unattributed_quantity: "0.500001", owners_truncated: false },
  }],
});
const hook = (locationId = 11) => renderHook(
  ({ warehouse }) => useLiveStockBatchDetail(
    warehouse, "Batch load failed", "Previously loaded details are stale",
  ),
  { initialProps: { warehouse: locationId } },
);
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const getCalls = (piece: string) =>
  mocks.authFetch.mock.calls.filter(([url]) => String(url).includes(piece));

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.language = "en";
});
afterEach(cleanup);

describe("L-02 detail freshness and NEW-03 disclosure", () => {
  it("invalidates old batches and source on refresh and verifies only the selected product", async () => {
    let batchReads = 0;
    mocks.authFetch.mockImplementation((url: string) => {
      if (url.includes("/source?")) return Promise.resolve(sourcePayload());
      if (url.includes("/batches?")) return Promise.resolve(batchPage(++batchReads === 1 ? "2.500001" : "3.500001"));
      throw Error("unexpected read");
    });
    const { result } = hook();
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page?.batches[0].on_hand_quantity).toBe("2.500001"));
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceByBatch[71]?.statuses[0].on_hand_quantity).toBe("2.500001"));

    act(() => result.current.invalidate());
    expect(result.current.page).toBeNull();
    expect(result.current.sourceOpenId).toBeNull();
    expect(result.current.sourceByBatch).toEqual({});
    expect(result.current.loadError?.kind).toBe("initial");
    expect(getCalls("/batches?")).toHaveLength(1);

    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.page?.batches[0].on_hand_quantity).toBe("3.500001"));
    expect(result.current.sourceByBatch).toEqual({});
    expect(getCalls("/batches?")).toHaveLength(2);
    expect(getCalls("/source?")).toHaveLength(1);
  });

  it("opens, closes, and reopens source with a new request; cached evidence cannot force expanded", async () => {
    mocks.authFetch.mockImplementation((url: string) => url.includes("/source?")
      ? Promise.resolve(sourcePayload("2.500001"))
      : Promise.resolve(batchPage()));
    const { result } = hook();
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceByBatch[71]).toBeTruthy());
    expect(result.current.sourceOpenId).toBe(71);

    act(() => result.current.loadSource(71));
    expect(result.current.sourceOpenId).toBeNull();
    expect(result.current.sourceByBatch).toEqual({});

    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceByBatch[71]).toBeTruthy());
    expect(result.current.sourceOpenId).toBe(71);
    expect(getCalls("/source?")).toHaveLength(2);
  });

  it("clears source evidence on a 5xx without inventing an authority revocation", async () => {
    const denied = vi.fn();
    let sourceReads = 0;
    mocks.authFetch.mockImplementation((url: string) => {
      if (!url.includes("/source?")) return Promise.resolve(batchPage());
      sourceReads += 1;
      return sourceReads === 1
        ? Promise.resolve(sourcePayload())
        : Promise.reject(Object.assign(new Error("server failure"), { status: 500 }));
    });
    const { result } = renderHook(() => useLiveStockBatchDetail(
      11, "Batch load failed", "Stale", denied));

    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceByBatch[71]).toBeTruthy());

    act(() => result.current.loadSource(71));
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceErrorId).toBe(71));
    expect(result.current.sourceByBatch).toEqual({});
    expect(result.current.page).not.toBeNull();
    expect(denied).not.toHaveBeenCalled();
  });

  it("keeps retry available after a source failure and requires a new successful read", async () => {
    mocks.authFetch.mockImplementation((url: string) => {
      if (url.includes("/source?")) {
        return getCalls("/source?").length === 1
          ? Promise.reject(new Error("offline")) : Promise.resolve(sourcePayload());
      }
      return Promise.resolve(batchPage());
    });
    const { result } = hook();
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceErrorId).toBe(71));
    expect(result.current.sourceOpenId).toBe(71);
    act(() => result.current.retrySource(71));
    await waitFor(() => expect(result.current.sourceByBatch[71]).toBeTruthy());
    expect(result.current.sourceErrorId).toBeNull();
    expect(getCalls("/source?")).toHaveLength(2);
  });

  it("aborts a delayed source response on collapse, ignoring late evidence", async () => {
    const delayed = deferred<ReturnType<typeof sourcePayload>>();
    mocks.authFetch.mockImplementation((url: string) =>
      url.includes("/source?") ? delayed.promise : Promise.resolve(batchPage()));
    const { result } = hook();
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    expect(getCalls("/source?")).toHaveLength(1);
    const requestOptions = getCalls("/source?")[0][1] as { signal: AbortSignal };
    act(() => result.current.loadSource(71));
    expect(requestOptions.signal.aborted).toBe(true);
    await act(async () => { delayed.resolve(sourcePayload()); await delayed.promise; });
    expect(result.current.sourceOpenId).toBeNull();
    expect(result.current.sourceByBatch).toEqual({});
  });

  it("aborts delayed batch response on warehouse switch and never mixes identities", async () => {
    const delayed = deferred<ReturnType<typeof batchPage>>();
    mocks.authFetch.mockReturnValueOnce(delayed.promise);
    const { result, rerender } = hook();
    act(() => result.current.open(product));
    const prior = getCalls("/batches?")[0][1] as { signal: AbortSignal };
    rerender({ warehouse: 12 });
    await waitFor(() => expect(prior.signal.aborted).toBe(true));
    await act(async () => { delayed.resolve(batchPage()); await delayed.promise; });
    expect(result.current.product).toBeNull();
    expect(result.current.page).toBeNull();
  });

  it("fails closed after detail or source access revocation and rejects wrong source identities", async () => {
    let blocked = false;
    mocks.authFetch.mockImplementation((url: string) => {
      if (blocked) return Promise.reject(Object.assign(new Error("forbidden"), { status: 403 }));
      if (url.includes("/source?")) return Promise.resolve(sourcePayload());
      return Promise.resolve(batchPage());
    });
    const { result } = hook();
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    blocked = true;
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.page).toBeNull());
    expect(result.current.sourceByBatch).toEqual({});
    expect(result.current.sourceOpenId).toBeNull();
    expect(result.current.loadError?.kind).toBe("initial");

    act(() => result.current.retry());
    await waitFor(() => expect(getCalls("/batches?")).toHaveLength(2));
    expect(result.current.page).toBeNull();

    blocked = false;
    mocks.authFetch.mockImplementation((url: string) =>
      url.includes("/source?") ? Promise.resolve(sourcePayload("2.500001", 71, 12))
        : Promise.resolve(batchPage()));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceErrorId).toBe(71));
    expect(result.current.sourceByBatch).toEqual({});
  });

  it("provides accessible source disclosure, keyboard focus, and RTL/LTR without changing amounts", () => {
    const onLoadSource = vi.fn();
    const onRetrySource = vi.fn();
    const props = {
      product,
      batches: parseBatchDetailResponse(batchPage()).batches,
      hasMore: false, loading: false, error: null,
      sourceByBatch: { 71: parseLiveStockWarehouseSource(sourcePayload()) },
      sourceLoadingId: null, sourceErrorId: null,
      onClose: vi.fn(), onRetry: vi.fn(), onLoadMore: vi.fn(),
      onLoadSource, onRetrySource,
    };
    const { rerender } = render(<BatchDetailPanel {...props} sourceOpenId={71} />);
    fireEvent.click(screen.getByText("Additional stock and reservation details"));
    const toggle = screen.getByRole("button", { name: "Stock and reservation details" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const target = toggle.getAttribute("aria-controls");
    expect(target).toBeTruthy();
    expect(document.getElementById(target!)).not.toBeNull();
    toggle.focus();
    expect(toggle).toHaveFocus();
    fireEvent.click(toggle);
    expect(onLoadSource).toHaveBeenCalledWith(71);

    rerender(<BatchDetailPanel {...props} sourceOpenId={null} />);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).not.toHaveAttribute("aria-controls");
    expect(screen.queryByText(/Warehouse 11/)).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();

    mocks.language = "ar";
    rerender(<BatchDetailPanel {...props} sourceOpenId={71} sourceErrorId={71} sourceByBatch={{}} />);
    expect(screen.getByRole("dialog")).toHaveAttribute("dir", "rtl");
    fireEvent.click(screen.getByRole("button", { name: "إعادة المحاولة" }));
    expect(onRetrySource).toHaveBeenCalledWith(71);
    expect(screen.getByRole("button", { name: "تفاصيل الكمية والحجوزات" }))
      .toHaveAttribute("aria-expanded", "true");
  });

  it("propagates an authorization denial to the warehouse disclosure owner", async () => {
    const denied = vi.fn();
    mocks.authFetch.mockImplementation((url: string) => url.includes("/source?")
      ? Promise.reject(Object.assign(new Error("revoked"), { status: 403 }))
      : Promise.resolve(batchPage()));
    const { result } = renderHook(() => useLiveStockBatchDetail(
      11, "Batch load failed", "Stale", denied));
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(denied).toHaveBeenCalledTimes(1));
    expect(result.current.page).toBeNull();
    expect(result.current.sourceByBatch).toEqual({});
  });

  it.each([401, 404])("fails the whole disclosure closed for HTTP %s authority loss", async (status) => {
    const denied = vi.fn();
    let deny = false;
    mocks.authFetch.mockImplementation((url: string) => {
      if (deny) return Promise.reject(Object.assign(new Error("authority lost"), { status }));
      return url.includes("/source?") ? Promise.resolve(sourcePayload()) : Promise.resolve(batchPage());
    });
    const { result } = renderHook(() => useLiveStockBatchDetail(
      11, "Batch load failed", "Stale", denied));

    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(result.current.sourceByBatch[71]).toBeTruthy());

    deny = true;
    act(() => result.current.loadSource(71));
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(denied).toHaveBeenCalledTimes(1));
    expect(result.current.page).toBeNull();
    expect(result.current.sourceByBatch).toEqual({});
    expect(result.current.sourceOpenId).toBeNull();

    act(() => result.current.retry());
    await waitFor(() => expect(denied).toHaveBeenCalledTimes(2));
    expect(result.current.page).toBeNull();
    expect(result.current.loadError?.kind).toBe("initial");
  });

  it("offers an in-dialog refresh without closing or reusing source evidence", () => {
    const onRefresh = vi.fn();
    render(<BatchDetailPanel product={product} batches={[]} hasMore={false}
      loading={false} error={null} sourceByBatch={{}} sourceLoadingId={null}
      sourceErrorId={null} onClose={vi.fn()} onRetry={vi.fn()}
      onLoadMore={vi.fn()} onLoadSource={vi.fn()} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: "inventoryShell.refreshNow" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});


describe("in-flight subordinate evidence ordering", () => {
  it("does not restore a pending batch continuation after source403 revokes disclosure", async () => {
    const delayed = deferred<ReturnType<typeof batchPage>>();
    const denied = vi.fn(); let reads = 0;
    mocks.authFetch.mockImplementation((url: string) => {
      if (url.includes("/source?")) return Promise.reject(Object.assign(new Error("revoked"), { status: 403 }));
      return ++reads === 1 ? Promise.resolve({ ...batchPage(), next_cursor: "more", has_more: true }) : delayed.promise;
    });
    const { result } = renderHook(() => useLiveStockBatchDetail(11, "failed", "stale", denied));
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page?.has_more).toBe(true));
    act(() => result.current.loadMore());
    const signal = getCalls("/batches?")[1][1].signal as AbortSignal;
    act(() => result.current.loadSource(71));
    await waitFor(() => expect(denied).toHaveBeenCalledTimes(1));
    expect(signal.aborted).toBe(true);
    await act(async () => delayed.resolve(batchPage()));
    expect(result.current.page).toBeNull();
    expect(result.current.sourceByBatch).toEqual({});
  });

  it("ignores an old product source after a different product is selected", async () => {
    const old = deferred<ReturnType<typeof sourcePayload>>();
    let reads = 0;
    mocks.authFetch.mockImplementation((url: string) => {
      if (url.includes("/source?")) return old.promise;
      return Promise.resolve(++reads === 1 ? batchPage() : {
        ...batchPage(), product_variant_id: 42,
        batches: [{ ...batchRaw(), batch_id: 72 }],
      });
    });
    const { result } = hook();
    act(() => result.current.open(product));
    await waitFor(() => expect(result.current.page).not.toBeNull());
    act(() => result.current.loadSource(71));
    const signal = getCalls("/source?")[0][1].signal as AbortSignal;
    act(() => result.current.open({ ...product, id: 42, name: "Product 42" }));
    await waitFor(() => expect(result.current.page?.product_variant_id).toBe(42));
    expect(signal.aborted).toBe(true);
    await act(async () => old.resolve(sourcePayload()));
    expect(result.current.product?.id).toBe(42);
    expect(result.current.sourceByBatch).toEqual({});
  });
});
