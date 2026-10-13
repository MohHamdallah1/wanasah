import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ deactivate: vi.fn(), reactivate: vi.fn(), invalidate: vi.fn() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => vi.fn() }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: mocks.invalidate }) }));
vi.mock("./api", () => ({ deactivateRepresentative: mocks.deactivate, reactivateRepresentative: mocks.reactivate }));
vi.mock("./representativeErrorMessage", () => ({ representativeErrorMessage: () => "retry" }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/ui/modal", () => ({ Modal: ({ isOpen, children, footer }: {
  isOpen: boolean; children: ReactNode; footer: ReactNode;
}) => isOpen ? <div>{children}{footer}</div> : null }));

import { RepresentativeLifecycleActions } from "./RepresentativeLifecycleActions";

afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

describe("Representative lifecycle lost-response retry", () => {
  it("replays the confirmed operation when reconnect refresh changes the current active state", async () => {
    const uuid = "11111111-1111-4111-8111-111111111111";
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => uuid) });
    mocks.deactivate.mockRejectedValueOnce({ status: 408, code: "REQUEST_TIMEOUT" }).mockResolvedValueOnce(undefined);
    const representative = { id: 17, full_name: "Representative", username: "rep17", phone_number: null,
      is_active: true, can_allow_debt: false, max_debt_limit: "0.000" };
    const view = render(<RepresentativeLifecycleActions representative={representative} allowed />);
    fireEvent.click(screen.getByText("representativesVehicles.representatives.lifecycle.deactivate"));
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.deactivate).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("common.confirm")).not.toBeDisabled());
    view.rerender(<RepresentativeLifecycleActions representative={{ ...representative, is_active: false }} allowed />);
    fireEvent.click(screen.getByText("common.confirm"));
    await waitFor(() => expect(mocks.deactivate).toHaveBeenCalledTimes(2));
    expect(mocks.deactivate.mock.calls.map((args) => args.slice(1))).toEqual([[17, uuid], [17, uuid]]);
    expect(mocks.reactivate).not.toHaveBeenCalled();
  });
});
