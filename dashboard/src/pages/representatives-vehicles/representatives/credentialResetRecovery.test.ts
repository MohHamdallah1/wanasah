import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  prepareCredentialReset,
  clearCredentialResetRecovery,
} from "./credentialResetRecovery";

const first = "22222222-2222-4222-8222-222222222222";
const second = "33333333-3333-4333-8333-333333333333";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "11");
  vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValueOnce(first).mockReturnValue(second) });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe("credential reset recovery scope", () => {
  it.each(["representative", "company", "principal"])("cannot reuse an unresolved request across %s scope", (dimension) => {
    const original = prepareCredentialReset(17);
    let target = 17;
    if (dimension === "representative") target = 18;
    if (dimension === "company") localStorage.setItem("company_id", "2");
    if (dimension === "principal") localStorage.setItem("principal_id", "12");
    const other = prepareCredentialReset(target);
    expect(other.requestId).toBe(second);
    clearCredentialResetRecovery(other);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "11");
    expect(prepareCredentialReset(17)).toEqual({ ...original, recovered: true });
  });

  it("does not consume another mutation family's recovery identity", () => {
    sessionStorage.setItem("wanasah:representative-deactivate:v1:1:11:17", second);
    expect(prepareCredentialReset(17).requestId).toBe(first);
    expect(sessionStorage.getItem("wanasah:representative-deactivate:v1:1:11:17")).toBe(second);
  });

  it("fails closed without canonical scope or writable recovery storage", () => {
    localStorage.removeItem("principal_id");
    expect(() => prepareCredentialReset(17)).toThrow();
    expect(crypto.randomUUID).not.toHaveBeenCalled();
    localStorage.setItem("principal_id", "11");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(() => prepareCredentialReset(17)).toThrow();
    expect(sessionStorage.length).toBe(0);
  });
});
