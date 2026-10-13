import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  getRepresentative: vi.fn(),
  useQuery: vi.fn(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("./api", () => ({ getRepresentative: mocks.getRepresentative }));
vi.mock("@tanstack/react-query", () => ({ useQuery: mocks.useQuery }));

import { useRepresentativeDetail } from "./useRepresentativeDetail";

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.getRepresentative.mockReset();
  mocks.useQuery.mockReset();
  mocks.getRepresentative.mockResolvedValue({ id: 17 });
  mocks.useQuery.mockReturnValue({ data: undefined });
});

describe("useRepresentativeDetail", () => {
  it("loads GET detail only while a representative drawer is enabled", async () => {
    let options: Record<string, unknown> | null = null;
    mocks.useQuery.mockImplementation((value: Record<string, unknown>) => {
      options = value;
      return { data: undefined };
    });

    renderHook(() => useRepresentativeDetail(17, true));

    expect(options?.queryKey).toEqual(["representative-detail", 17]);
    expect(options?.enabled).toBe(true);
    expect(options?.gcTime).toBe(0);

    const queryFn = options?.queryFn as (args: { signal: AbortSignal | undefined }) => Promise<unknown>;
    await queryFn({ signal: undefined });
    expect(mocks.getRepresentative).toHaveBeenCalledWith(mocks.authFetch, 17, undefined);
  });

  it("keeps the detail query disabled after the drawer closes", () => {
    let options: Record<string, unknown> | null = null;
    mocks.useQuery.mockImplementation((value: Record<string, unknown>) => {
      options = value;
      return { data: undefined };
    });

    renderHook(() => useRepresentativeDetail(17, false));
    expect(options?.enabled).toBe(false);
  });
});
