import {
  act,
  cleanup,
  renderHook,
} from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type {
  QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
  },
}));
vi.mock("@/pages/products/contracts", async (importOriginal) => {
  const original = await importOriginal<
    typeof import("@/pages/products/contracts")
  >();
  return {
    ...original,
    parseProductImportState: (value: unknown) => value,
  };
});

import {
  useImportProductPolling,
} from "@/pages/products/import/useImportProductPolling";

const JOB = "11111111-1111-4111-8111-111111111111";

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: FakeSocket[] = [];

  readonly url: string;
  readyState = FakeSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  sent: string[] = [];
  closed = 0;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  send(value: string) {
    this.sent.push(value);
  }

  close() {
    this.closed += 1;
    this.readyState = 3;
  }

  fireOpen() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  fireClose() {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }

  fireMessage(payload: object) {
    this.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify(payload),
      }),
    );
  }
}

const statuses = {
  importing: {
    status: "IMPORTING",
    imported_rows: 0,
    invalid_rows: 0,
    import_failed_rows: 0,
    default_lot_control_mode: "NONE",
    default_expiry_control_mode: "NONE",
  },
  completed: {
    status: "COMPLETED",
    imported_rows: 1,
    invalid_rows: 0,
    import_failed_rows: 0,
    default_lot_control_mode: "NONE",
    default_expiry_control_mode: "NONE",
  },
};

const setStatus = vi.fn();
const setError = vi.fn();
const setTracking = vi.fn();
const setMapping = vi.fn();

function mount(authFetch: (path: string) => Promise<unknown>) {
  const queryClient = {
    invalidateQueries: vi.fn().mockResolvedValue(undefined),
  } as unknown as QueryClient;
  return renderHook(() =>
    useImportProductPolling({
      enabled: true,
      importJobId: JOB,
      importPollKey: 0,
      setImportPollKey: vi.fn(),
      authFetch,
      queryClient,
      t: ((key: string) => key) as TFunction,
      isOnline: true,
      setImportPollError: setError,
      setImportStatus: setStatus,
      setImportLotControlMode: setTracking,
      setImportExpiryControlMode: setTracking,
      setMapping,
    }),
  );
}

let visibility: DocumentVisibilityState = "visible";
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
  FakeSocket.instances = [];
  localStorage.setItem("admin_token", "synthetic-test-token");
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  setStatus.mockClear();
  setError.mockClear();
  setTracking.mockClear();
  setMapping.mockClear();
});

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.removeItem("admin_token");
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
});

describe("Product Import live-progress transport lifecycle", () => {
  it("does not schedule a second socket when an obsolete socket closes late", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("offline-test"));
    const hook = mount(fetch);

    expect(FakeSocket.instances).toHaveLength(1);
    const oldSocket = FakeSocket.instances[0];
    act(() => {
      oldSocket.fireOpen();
    });
    expect(oldSocket.sent).toEqual([
      JSON.stringify({
        type: "auth",
        token: "synthetic-test-token",
      }),
    ]);

    // Simulate a tab hidden, then visible before the browser dispatches
    // the old socket's asynchronous close event.
    act(() => {
      visibility = "hidden";
      document.dispatchEvent(new Event("visibilitychange"));
      visibility = "visible";
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(FakeSocket.instances).toHaveLength(2);
    const currentSocket = FakeSocket.instances[1];

    act(() => {
      currentSocket.fireOpen();
      currentSocket.fireMessage({ event: "WS_AUTHENTICATED" });
    });
    act(() => {
      oldSocket.fireClose();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1800);
    });
    expect(FakeSocket.instances).toHaveLength(2);
    expect(currentSocket.closed).toBe(0);

    // A real current socket failure must still reconnect exactly once.
    act(() => {
      currentSocket.fireClose();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1800);
    });
    expect(FakeSocket.instances).toHaveLength(3);

    hook.unmount();
  });

  it("cannot revert a completed import to a stale in-flight HTTP snapshot", async () => {
    let resolveEarlier!: (status: unknown) => void;
    const firstRequest = new Promise<unknown>((resolve) => {
      resolveEarlier = resolve;
    });
    const fetch = vi.fn()
      .mockReturnValueOnce(firstRequest)
      .mockResolvedValue(statuses.completed);
    const hook = mount(fetch);
    const socket = FakeSocket.instances[0];
    await act(async () => {
      socket.fireOpen();
      await Promise.resolve();
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(setStatus).toHaveBeenCalledWith(statuses.completed);

    await act(async () => {
      resolveEarlier(statuses.importing);
      await Promise.resolve();
    });
    expect(setStatus).toHaveBeenCalledTimes(1);
    expect(setStatus).toHaveBeenLastCalledWith(statuses.completed);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(32000);
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    hook.unmount();
  });

  it("ignores an obsolete HTTP error that arrives after confirmed completion", async () => {
    let rejectEarlier!: (reason: Error) => void;
    const olderRequest = new Promise<unknown>((_resolve, reject) => {
      rejectEarlier = reject;
    });
    const fetch = vi.fn()
      .mockReturnValueOnce(olderRequest)
      .mockResolvedValue(statuses.completed);
    const hook = mount(fetch);

    await act(async () => {
      FakeSocket.instances[0].fireOpen();
      await Promise.resolve();
    });
    expect(setStatus).toHaveBeenLastCalledWith(statuses.completed);
    expect(setError).toHaveBeenCalledTimes(1);
    expect(setError).toHaveBeenLastCalledWith(null);

    await act(async () => {
      rejectEarlier(new Error("late request failed"));
      await Promise.resolve();
    });
    // The completed view must not redisplay a stale error or restart polling.
    expect(setError).toHaveBeenCalledTimes(1);
    expect(setError).toHaveBeenLastCalledWith(null);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(32000);
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    hook.unmount();
  });
});
