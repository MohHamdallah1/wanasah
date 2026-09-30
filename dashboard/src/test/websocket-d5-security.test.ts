import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const dispatch = read("../pages/DispatchBoard.tsx");
const importFeed = read("../pages/products/import/useImportProductPolling.ts");

describe("D5 WebSocket credential and reconnect contract", () => {
  it("never appends access tokens to either WebSocket URL", () => {
    expect(dispatch).toContain("/ws/dispatch");
    expect(importFeed).toContain("/simple-products/imports/");
    expect(dispatch).not.toContain("/ws/dispatch?token=");
    expect(importFeed).not.toContain("/ws?token=");
    expect(dispatch).not.toContain("encodeURIComponent(token)");
    expect(importFeed).not.toContain("encodeURIComponent(\n              token");
  });

  it("authenticates in the first frame after handshake, not via URL or protocol", () => {
    expect(dispatch).toContain('type: "auth", token: liveToken');
    expect(importFeed).toContain('type: "auth",');
    expect(dispatch).toContain("ws?.send(JSON.stringify(");
    expect(importFeed).toContain("nextSocket.send(");
  });

  it("uses fresh access credentials when reconnecting", () => {
    expect(dispatch).toContain('localStorage.getItem("admin_token")');
    expect(importFeed).toContain('"admin_token"');
    expect(dispatch).toContain("ws.onopen = () =>");
    expect(importFeed).toContain("nextSocket.onopen =");
  });

  it("keeps import HTTP fallback until server acknowledges authorized scope", () => {
    const connectSegment = importFeed.slice(
      importFeed.indexOf("nextSocket.onopen"),
      importFeed.indexOf("nextSocket.onmessage"),
    );
    expect(connectSegment).not.toContain("realtimeOpen =\n              true");
    const messageSegment = importFeed.slice(
      importFeed.indexOf("nextSocket.onmessage"),
      importFeed.indexOf("nextSocket.onclose"),
    );
    expect(messageSegment).toContain("WS_AUTHENTICATED");
    expect(messageSegment).toContain("websocket !==");
    expect(messageSegment).toContain("realtimeOpen =");
    expect(messageSegment).toContain("scheduleRealtimeRefresh");
  });

  it("ignores the auth-ack control event in the dispatch data refresh stream", () => {
    expect(dispatch).toContain('data.event === "WS_AUTHENTICATED"');
  });
});
