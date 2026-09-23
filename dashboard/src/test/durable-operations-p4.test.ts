import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  durableScope,
  getOrCreateDurableCommand,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";

describe(
  "durable command P4 legacy promotion",
  () => {
    beforeEach(() => {
      localStorage.clear();
      vi.restoreAllMocks();
    });

    it("promotes a matching legacy request without changing request identity", async () => {
      const scope = durableScope(
        1,
        2,
        "family-create",
      );
      const payload = {
        name: "Alpha Family",
      };

      const legacyRequestId =
        await getOrCreateDurableRequestId(
          scope,
          payload,
        );

      const command =
        await getOrCreateDurableCommand(
          scope,
          payload,
        );

      expect(
        command.requestId,
      ).toBe(legacyRequestId);
      expect(
        command.payload,
      ).toEqual(payload);

      const raw =
        localStorage.getItem(scope);
      expect(raw).not.toBeNull();
      expect(
        JSON.parse(String(raw)),
      ).toMatchObject({
        kind: "command",
        requestId:
          legacyRequestId,
        payload,
      });
    });

    it("does not replace a legacy unresolved request when the payload changed", async () => {
      const scope = durableScope(
        1,
        2,
        "family-create",
      );

      const legacyRequestId =
        await getOrCreateDurableRequestId(
          scope,
          {
            name: "Alpha Family",
          },
        );

      await expect(
        getOrCreateDurableCommand(
          scope,
          {
            name: "Beta Family",
          },
        ),
      ).rejects.toMatchObject({
        code:
          "DURABLE_OPERATION_PENDING",
      });

      const stored = JSON.parse(
        String(
          localStorage.getItem(
            scope,
          ),
        ),
      ) as {
        kind: string;
        requestId: string;
      };

      expect(stored.kind).toBe(
        "request",
      );
      expect(
        stored.requestId,
      ).toBe(legacyRequestId);
    });
  },
);
