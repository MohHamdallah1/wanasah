import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => vi.fn() }));
vi.mock("./api", () => ({ listRepresentatives: mocks.list }));

import { useRepresentatives } from "./useRepresentatives";

const row = { id: 17, full_name: "Previous session", username: "previous", phone_number: null,
  is_active: true, can_allow_debt: false, max_debt_limit: "0.000" };

function session(company: string, principal: string) {
  localStorage.setItem("company_id", company);
  localStorage.setItem("principal_id", principal);
}

afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

describe("Representative session cache isolation", () => {
  it("never retains another company or principal's list after a denied SPA re-login", async () => {
    for (const next of [["2", "21"], ["1", "12"]]) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
      session("1", "11");
      mocks.list.mockResolvedValue({ items: [row], next_cursor: null, has_more: false });
      const previous = renderHook(() => useRepresentatives(), { wrapper });
      await waitFor(() => expect(previous.result.current.items).toEqual([row]));
      previous.unmount(); // Forced logout uses SPA navigation; QueryClient survives.
      session(next[0], next[1]);
      mocks.list.mockRejectedValue({ status: 403, code: "PERMISSION_DENIED" });
      const current = renderHook(() => useRepresentatives(), { wrapper });
      expect(current.result.current.items).toEqual([]);
      await waitFor(() => expect(current.result.current.query.isError).toBe(true));
      expect(current.result.current.items).toEqual([]);
      current.unmount();
      client.clear();
    }
  });
});
