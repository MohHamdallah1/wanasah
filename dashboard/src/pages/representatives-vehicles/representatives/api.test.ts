import { describe, expect, it, vi } from "vitest";

import {
  createRepresentative,
  deactivateRepresentative,
  listRepresentatives,
  resetRepresentativeCredentials,
  updateRepresentative,
} from "./api";

const representative = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: null,
  is_active: true,
  can_allow_debt: false,
  max_debt_limit: "0.000",
};

const requestUuid = "11111111-1111-4111-8111-111111111111";

describe("representative API wire contract", () => {
  it("omits active for the all filter", async () => {
    const authFetch = vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false });
    await listRepresentatives(authFetch, { search: "", status: "all" });
    expect(authFetch).toHaveBeenCalledWith(
      "/representatives?limit=30",
      { signal: undefined },
    );
  });

  it("maps active and inactive filters exactly to true and false", async () => {
    const authFetch = vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false });

    await listRepresentatives(authFetch, { search: "", status: "active" });
    await listRepresentatives(authFetch, { search: "", status: "inactive" });

    expect(authFetch.mock.calls[0]?.[0]).toBe("/representatives?active=true&limit=30");
    expect(authFetch.mock.calls[1]?.[0]).toBe("/representatives?active=false&limit=30");
  });

  it("uses frozen list query names and cursor envelope", async () => {
    const authFetch = vi.fn().mockResolvedValue({ items: [representative], next_cursor: null, has_more: false });
    await listRepresentatives(authFetch, { search: "ah", status: "active", cursor: "opaque", limit: 30 });
    expect(authFetch).toHaveBeenCalledWith(
      "/representatives?search=ah&active=true&cursor=opaque&limit=30",
      { signal: undefined },
    );
  });

  it("does not send a one-character search rejected by the frozen contract", async () => {
    const authFetch = vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false });
    await listRepresentatives(authFetch, { search: "a", status: "all" });
    expect(authFetch.mock.calls[0]?.[0]).toBe("/representatives?limit=30");
  });

  it("preserves request_id and required phone while sending minimal update fields", async () => {
    const authFetch = vi.fn().mockResolvedValue(representative);

    await createRepresentative(authFetch, {
      full_name: "Ahmad Saleh",
      username: "rep17",
      phone_number: "+962790000000",
      password: "password8",
      can_allow_debt: false,
      max_debt_limit: "0.000",
    }, requestUuid);
    const createBody = JSON.parse(String((authFetch.mock.calls[0]?.[1] as RequestInit).body));
    expect(createBody).toEqual({
      request_id: requestUuid,
      full_name: "Ahmad Saleh",
      username: "rep17",
      phone_number: "+962790000000",
      password: "password8",
      can_allow_debt: false,
      max_debt_limit: "0.000",
    });
    expect(createBody).not.toHaveProperty("confirm_password");

    await updateRepresentative(authFetch, 17, { phone_number: "0791111111" }, requestUuid);
    const updateBody = JSON.parse(String((authFetch.mock.calls[1]?.[1] as RequestInit).body));
    expect(updateBody).toEqual({ request_id: requestUuid, phone_number: "0791111111" });
    expect(updateBody).not.toHaveProperty("password");
    expect(updateBody).not.toHaveProperty("is_active");
  });

  it("uses caller-owned idempotency keys for lifecycle and credential reset", async () => {
    const authFetch = vi.fn().mockResolvedValue(null);

    await deactivateRepresentative(authFetch, 17, requestUuid);
    expect(JSON.parse(String((authFetch.mock.calls[0]?.[1] as RequestInit).body))).toEqual({ request_id: requestUuid });

    await resetRepresentativeCredentials(authFetch, 17, "newpass88", requestUuid);
    expect(JSON.parse(String((authFetch.mock.calls[1]?.[1] as RequestInit).body))).toEqual({
      request_id: requestUuid,
      new_password: "newpass88",
    });
  });
});
