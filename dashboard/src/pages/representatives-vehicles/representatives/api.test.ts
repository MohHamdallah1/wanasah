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

  it("preserves the caller-owned request_id for create and update", async () => {
    const authFetch = vi.fn().mockResolvedValue(representative);

    await createRepresentative(authFetch, {
      full_name: "Ahmad Saleh",
      username: "rep17",
      phone_number: null,
      password: "password8",
      can_allow_debt: false,
      max_debt_limit: "0.000",
    }, requestUuid);
    const createBody = JSON.parse(String((authFetch.mock.calls[0]?.[1] as RequestInit).body));
    expect(createBody).toEqual({
      request_id: requestUuid,
      full_name: "Ahmad Saleh",
      username: "rep17",
      phone_number: null,
      password: "password8",
      can_allow_debt: false,
      max_debt_limit: "0.000",
    });

    await updateRepresentative(authFetch, 17, {
      full_name: "Ahmad S.",
      username: "rep17b",
      phone_number: "+962790000000",
      can_allow_debt: true,
      max_debt_limit: "20.000",
    }, requestUuid);
    const updateBody = JSON.parse(String((authFetch.mock.calls[1]?.[1] as RequestInit).body));
    expect(updateBody.request_id).toBe(requestUuid);
    expect(updateBody.username).toBe("rep17b");
    expect(updateBody).not.toHaveProperty("password");
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
