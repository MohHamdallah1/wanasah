import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchNextPage: vi.fn(),
  refetch: vi.fn(),
  invalidateQueries: vi.fn(),
  infiniteScroll: vi.fn(),
  useRepresentatives: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => vi.fn() }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({ isCompanyOwner: false, isLoading: false, can: () => false }),
}));
vi.mock("@/lib/apiErrors", () => ({ apiErrorMessage: () => "load-error" }));
vi.mock("./api", () => ({ createRepresentative: vi.fn() }));
vi.mock("./representativeErrorMessage", () => ({ representativeErrorMessage: () => "save-error" }));
vi.mock("./useRepresentatives", () => ({ useRepresentatives: mocks.useRepresentatives }));
vi.mock("./useRepresentativeInfiniteScroll", () => ({
  useRepresentativeInfiniteScroll: (options: unknown) => {
    mocks.infiniteScroll(options);
    return { sentinelRef: vi.fn(), manualFallback: false };
  },
}));
vi.mock("./RepresentativeTable", () => ({
  RepresentativeTable: ({ items }: { items: Array<{ full_name: string }> }) => (
    <div data-testid="representative-table">{items.map((item) => item.full_name).join(",")}</div>
  ),
}));
vi.mock("./RepresentativeDrawer", () => ({ RepresentativeDrawer: () => null }));
vi.mock("./RepresentativeForm", () => ({ RepresentativeForm: () => null }));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children }: { isOpen: boolean; children: ReactNode }) => isOpen ? <>{children}</> : null,
}));

import { RepresentativesTab } from "./RepresentativesTab";

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
  mocks.fetchNextPage.mockReset();
  mocks.refetch.mockReset();
  mocks.invalidateQueries.mockReset();
  mocks.infiniteScroll.mockReset();
  mocks.useRepresentatives.mockReset();
  mocks.useRepresentatives.mockReturnValue({
    input: "",
    setInput: vi.fn(),
    status: "all",
    setStatus: vi.fn(),
    items: [representative],
    query: {
      isError: true,
      isFetchNextPageError: true,
      error: { status: 503 },
      isFetching: false,
      isFetchingNextPage: false,
      hasNextPage: true,
      fetchNextPage: mocks.fetchNextPage,
      refetch: mocks.refetch,
    },
  });
});

afterEach(cleanup);

describe("RepresentativesTab paging failure", () => {
  it("keeps loaded rows, stops automatic cursor retries, and offers a manual retry", () => {
    render(<RepresentativesTab />);

    expect(screen.getByTestId("representative-table").textContent).toContain("Ahmad Saleh");
    expect(screen.getByRole("alert").textContent).toContain("load-error");
    expect(mocks.infiniteScroll).toHaveBeenCalledWith(
      expect.objectContaining({ hasMore: false }),
    );

    fireEvent.click(screen.getByText("common.retry"));
    expect(mocks.fetchNextPage).toHaveBeenCalledTimes(1);
    expect(mocks.refetch).not.toHaveBeenCalled();
  });
});
