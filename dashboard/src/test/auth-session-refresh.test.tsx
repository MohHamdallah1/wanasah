import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  MemoryRouter,
} from "react-router-dom";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  readAccessTokenIfRefreshAdvanced,
} from "../lib/authStorage";
import {
  useAuthFetch,
} from "../hooks/useAuthFetch";


const fetchMock = vi.fn();

vi.stubGlobal("fetch", fetchMock);

function Harness() {
  const authFetch = useAuthFetch();

  return (
    <button
      type="button"
      onClick={async () => {
        const value = await authFetch("/protected");
        document.body.dataset.result =
          JSON.stringify(value);
      }}
    >
      run
    </button>
  );
}

describe("dashboard session refresh concurrency", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.dataset.result = "";
    fetchMock.mockReset();
  });

  afterEach(() => {
    localStorage.clear();
    document.body.dataset.result = "";
  });

  it("detects when another browser context already rotated the session", () => {
    localStorage.setItem(
      "admin_token",
      "new-access",
    );
    localStorage.setItem(
      "refresh_token",
      "new-refresh",
    );

    expect(
      readAccessTokenIfRefreshAdvanced(
        "old-refresh",
      ),
    ).toBe("new-access");

    expect(
      readAccessTokenIfRefreshAdvanced(
        "new-refresh",
      ),
    ).toBeNull();
  });

  it("does not erase a newer session when a stale refresh returns 401", async () => {
    localStorage.setItem(
      "admin_token",
      "expired-access",
    );
    localStorage.setItem(
      "refresh_token",
      "old-refresh",
    );

    fetchMock.mockImplementation(
      async (
        input: RequestInfo | URL,
        init?: RequestInit,
      ) => {
        const url = String(input);

        if (url.endsWith("/refresh")) {
          localStorage.setItem(
            "admin_token",
            "new-access",
          );
          localStorage.setItem(
            "refresh_token",
            "new-refresh",
          );
          return new Response(
            JSON.stringify({
              detail: "stale refresh",
            }),
            {
              status: 401,
              headers: {
                "Content-Type":
                  "application/json",
              },
            },
          );
        }

        const authorization = new Headers(
          init?.headers,
        ).get("Authorization");

        if (
          authorization ===
          "Bearer expired-access"
        ) {
          return new Response("", {
            status: 401,
          });
        }

        if (
          authorization ===
          "Bearer new-access"
        ) {
          return new Response(
            JSON.stringify({ ok: true }),
            {
              status: 200,
              headers: {
                "Content-Type":
                  "application/json",
              },
            },
          );
        }

        throw new Error(
          "Unexpected request: " + url,
        );
      },
    );

    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "run",
      }),
    );

    await waitFor(() => {
      expect(
        document.body.dataset.result,
      ).toBe('{"ok":true}');
    });

    expect(
      localStorage.getItem("admin_token"),
    ).toBe("new-access");
    expect(
      localStorage.getItem("refresh_token"),
    ).toBe("new-refresh");

    expect(
      fetchMock.mock.calls.some(
        ([input]) =>
          String(input).endsWith("/logout"),
      ),
    ).toBe(false);
  });
});
