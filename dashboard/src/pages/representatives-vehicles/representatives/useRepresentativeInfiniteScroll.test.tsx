import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useRepresentativeInfiniteScroll } from "./useRepresentativeInfiniteScroll";

let observerCallback: IntersectionObserverCallback | null = null;

class FakeIntersectionObserver {
  constructor(callback: IntersectionObserverCallback) {
    observerCallback = callback;
  }

  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
}

afterEach(() => {
  observerCallback = null;
  vi.unstubAllGlobals();
});

describe("useRepresentativeInfiniteScroll", () => {
  it("automatically requests the next cursor page when the sentinel intersects", async () => {
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    const onLoadMore = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useRepresentativeInfiniteScroll({
        hasMore: true,
        isFetchingNextPage: false,
        onLoadMore,
      }),
    );

    act(() => result.current.sentinelRef(document.createElement("div")));
    await waitFor(() => expect(observerCallback).not.toBeNull());

    act(() => {
      observerCallback?.(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    await waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(1));
  });

  it("does not duplicate a next-page request during repeated intersections", async () => {
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    let resolveLoad: (() => void) | undefined;
    const pendingLoad = new Promise<void>((resolve) => {
      resolveLoad = resolve;
    });
    const onLoadMore = vi.fn(() => pendingLoad);
    const { result } = renderHook(() =>
      useRepresentativeInfiniteScroll({
        hasMore: true,
        isFetchingNextPage: false,
        onLoadMore,
      }),
    );

    act(() => result.current.sentinelRef(document.createElement("div")));
    await waitFor(() => expect(observerCallback).not.toBeNull());

    act(() => {
      const entries = [{ isIntersecting: true } as IntersectionObserverEntry];
      observerCallback?.(entries, {} as IntersectionObserver);
      observerCallback?.(entries, {} as IntersectionObserver);
    });

    expect(onLoadMore).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveLoad?.();
      await pendingLoad;
    });
  });
});
