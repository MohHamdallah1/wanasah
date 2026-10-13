import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  listRepresentatives: vi.fn(),
  useInfiniteQuery: vi.fn(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("./api", () => ({ listRepresentatives: mocks.listRepresentatives }));
vi.mock("@tanstack/react-query", () => ({ useInfiniteQuery: mocks.useInfiniteQuery }));

import { useRepresentatives } from "./useRepresentatives";

const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: null,
  is_active: true,
  can_allow_debt: false,
  max_debt_limit: "0.000",
};

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.listRepresentatives.mockReset();
  mocks.useInfiniteQuery.mockReset();
  mocks.listRepresentatives.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
});

describe("useRepresentatives", () => {
  it("defaults to the all filter and requests the list with that wire state", async () => {
    let queryOptions: Record<string, unknown> | null = null;
    mocks.useInfiniteQuery.mockImplementation((options: Record<string, unknown>) => {
      queryOptions = options;
      return {
        data: { pages: [] },
        isFetching: false,
        isFetchingNextPage: false,
        hasNextPage: false,
      };
    });

    const { result } = renderHook(() => useRepresentatives());
    expect(result.current.status).toBe("all");

    const queryFn = queryOptions?.queryFn as ((args: { signal: AbortSignal | undefined; pageParam: string | null }) => Promise<unknown>);
    await queryFn({ signal: undefined, pageParam: null });
    expect(mocks.listRepresentatives).toHaveBeenCalledWith(
      mocks.authFetch,
      expect.objectContaining({ status: "all", cursor: null, limit: 30 }),
    );
  });

  it("deduplicates representative rows already loaded across cursor pages", () => {
    mocks.useInfiniteQuery.mockReturnValue({
      data: {
        pages: [
          { items: [representative], next_cursor: "next", has_more: true },
          {
            items: [representative, { ...representative, id: 18, username: "rep18" }],
            next_cursor: null,
            has_more: false,
          },
        ],
      },
      isFetching: false,
      isFetchingNextPage: false,
      hasNextPage: false,
    });

    const { result } = renderHook(() => useRepresentatives());
    expect(result.current.items.map((item) => item.id)).toEqual([17, 18]);
  });
});
