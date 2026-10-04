import { describe, expect, it } from "vitest";

import {
  createDispatchReservationFocusState,
  parseDispatchNavigationState,
} from "@/features/dispatch/navigation";

describe("dispatch reservation-owner navigation", () => {
  it("round-trips an exact route and handshake focus without browser storage", () => {
    const state = createDispatchReservationFocusState({
      routeId: 9,
      transferId: 77,
      openCancel: true,
    });

    expect(parseDispatchNavigationState(state)).toEqual({
      version: 1,
      kind: "reservation-owner",
      routeId: 9,
      transferId: 77,
      openCancel: true,
    });
  });

  it.each([
    null,
    {},
    { dispatchNavigation: { version: 1, kind: "reservation-owner", routeId: 0, transferId: 77, openCancel: true } },
    { dispatchNavigation: { version: 1, kind: "reservation-owner", routeId: 9, transferId: -1, openCancel: true } },
    { dispatchNavigation: { version: 1, kind: "reservation-owner", routeId: 9, transferId: 77, openCancel: "yes" } },
  ])("rejects malformed navigation evidence", (raw) => {
    expect(parseDispatchNavigationState(raw)).toBeNull();
  });
});
