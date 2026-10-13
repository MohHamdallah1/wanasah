import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Representative } from "./contracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  fetchNextPage: vi.fn(),
  refetch: vi.fn(),
  invalidateQueries: vi.fn(),
  setQueriesData: vi.fn(),
  infiniteScroll: vi.fn(),
  useRepresentatives: vi.fn(),
  createRepresentative: vi.fn(),
  updateRepresentative: vi.fn(),
  access: {
    owner: false,
    manage: false,
    credentials: false,
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: mocks.invalidateQueries,
    setQueriesData: mocks.setQueriesData,
  }),
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    isCompanyOwner: mocks.access.owner,
    isLoading: false,
    can: (capability: string) => capability === "representative.manage"
      ? mocks.access.manage
      : capability === "representative.credentials.reset"
        ? mocks.access.credentials
        : false,
  }),
}));
vi.mock("@/lib/apiErrors", () => ({ apiErrorMessage: () => "load-error" }));
vi.mock("./api", () => ({
  createRepresentative: mocks.createRepresentative,
  updateRepresentative: mocks.updateRepresentative,
}));
vi.mock("./representativeErrorMessage", () => ({ representativeErrorMessage: () => "load-error" }));
vi.mock("./useRepresentatives", () => ({ useRepresentatives: mocks.useRepresentatives }));
vi.mock("./useRepresentativeInfiniteScroll", () => ({
  useRepresentativeInfiniteScroll: (options: unknown) => {
    mocks.infiniteScroll(options);
    return { sentinelRef: vi.fn(), manualFallback: false };
  },
}));
vi.mock("./RepresentativeTable", () => ({
  RepresentativeTable: ({
    items,
    canManage,
    canResetCredentials,
    onEdit,
    onLifecycle,
    onResetCredentials,
  }: {
    items: Representative[];
    canManage: boolean;
    canResetCredentials: boolean;
    onEdit: (representative: Representative) => void;
    onLifecycle: (representative: Representative) => void;
    onResetCredentials: (representative: Representative) => void;
  }) => (
    <div data-testid="representative-table">
      {items.map((item) => item.full_name).join(",")}
      <button type="button" disabled={!canManage} onClick={() => onEdit(items[0])}>edit-row</button>
      <button type="button" disabled={!canManage} onClick={() => onLifecycle(items[0])}>lifecycle-row</button>
      <button type="button" disabled={!canResetCredentials} onClick={() => onResetCredentials(items[0])}>reset-row</button>
    </div>
  ),
}));
vi.mock("./RepresentativeForm", () => ({
  RepresentativeForm: ({ representative: current, onSubmit }: {
    representative?: Representative | null;
    onSubmit: (input: { full_name: string; username: string }, requestId: string) => void;
  }) => current ? (
    <div data-testid="edit-form">
      <span>{current.full_name}</span>
      <span>{current.username}</span>
      <button
        type="button"
        onClick={() => onSubmit({ full_name: "Ahmad Updated", username: "rep-updated" }, "edit-request")}
      >
        save-edit
      </button>
    </div>
  ) : <div data-testid="create-form" />,
}));
vi.mock("./RepresentativeLifecycleActions", () => ({
  RepresentativeLifecycleActions: ({ representative: current, open, onOpenChange }: {
    representative: Representative;
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }) => open ? (
    <div data-testid="lifecycle-controller">
      {current.is_active ? "deactivate" : "reactivate"}
      <button type="button" onClick={() => onOpenChange(false)}>close-lifecycle</button>
    </div>
  ) : null,
}));
vi.mock("./RepresentativeCredentialAction", () => ({
  RepresentativeCredentialAction: ({ open, onOpenChange }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }) => open ? (
    <div data-testid="credential-controller">
      credential-reset
      <button type="button" onClick={() => onOpenChange(false)}>close-credential</button>
    </div>
  ) : null,
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children }: { isOpen: boolean; children: ReactNode }) => isOpen ? <>{children}</> : null,
}));

import { RepresentativesTab } from "./RepresentativesTab";

const representative: Representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: null,
  is_active: true,
  can_allow_debt: false,
  max_debt_limit: "0.000",
};

beforeEach(() => {
  mocks.access.owner = false;
  mocks.access.manage = false;
  mocks.access.credentials = false;
  mocks.fetchNextPage.mockReset();
  mocks.refetch.mockReset();
  mocks.invalidateQueries.mockReset().mockResolvedValue(undefined);
  mocks.setQueriesData.mockReset();
  mocks.infiniteScroll.mockReset();
  mocks.useRepresentatives.mockReset();
  mocks.createRepresentative.mockReset();
  mocks.updateRepresentative.mockReset().mockResolvedValue({
    ...representative,
    full_name: "Ahmad Updated",
    username: "rep-updated",
  });
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

describe("RepresentativesTab", () => {
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

  it("opens edit mode directly with current name/username and saves through canonical PATCH client", async () => {
    mocks.access.manage = true;
    render(<RepresentativesTab />);

    fireEvent.click(screen.getByText("edit-row"));
    const form = screen.getByTestId("edit-form");
    expect(form).toHaveTextContent("Ahmad Saleh");
    expect(form).toHaveTextContent("rep17");

    fireEvent.click(screen.getByText("save-edit"));
    await waitFor(() => expect(mocks.updateRepresentative).toHaveBeenCalledWith(
      mocks.authFetch,
      17,
      { full_name: "Ahmad Updated", username: "rep-updated" },
      "edit-request",
    ));
    expect(mocks.setQueriesData).toHaveBeenCalled();
    await waitFor(() => expect(mocks.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["representatives"] }));
    await waitFor(() => expect(screen.queryByTestId("edit-form")).toBeNull());
  });

  it("opens lifecycle and credential controllers directly from semantic row actions", () => {
    mocks.access.manage = true;
    mocks.access.credentials = true;
    render(<RepresentativesTab />);

    fireEvent.click(screen.getByText("lifecycle-row"));
    expect(screen.getByTestId("lifecycle-controller")).toHaveTextContent("deactivate");
    fireEvent.click(screen.getByText("close-lifecycle"));
    expect(screen.queryByTestId("lifecycle-controller")).toBeNull();

    fireEvent.click(screen.getByText("reset-row"));
    expect(screen.getByTestId("credential-controller")).toHaveTextContent("credential-reset");
  });

  it("preserves independent manage and credential-reset capability gating", () => {
    mocks.access.manage = false;
    mocks.access.credentials = true;
    const first = render(<RepresentativesTab />);
    expect(screen.getByText("edit-row")).toBeDisabled();
    expect(screen.getByText("lifecycle-row")).toBeDisabled();
    expect(screen.getByText("reset-row")).not.toBeDisabled();
    first.unmount();

    mocks.access.manage = true;
    mocks.access.credentials = false;
    render(<RepresentativesTab />);
    expect(screen.getByText("edit-row")).not.toBeDisabled();
    expect(screen.getByText("lifecycle-row")).not.toBeDisabled();
    expect(screen.getByText("reset-row")).toBeDisabled();
  });
});
