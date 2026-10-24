import { useCallback, useRef, useState } from "react";

import {
  parseInboundOptions,
  type InboundOptionsResponse,
  type InboundVariantOptions,
} from "./contracts";

type AuthenticatedFetch = (
  url: string,
  opts?: RequestInit,
) => Promise<unknown>;

type ReadyInboundOptions = {
  options: Map<number, InboundVariantOptions>;
  asOfDate: string;
};

const normalizeIds = (ids: number[]) =>
  [...new Set(ids)]
    .filter((id) => Number.isSafeInteger(id) && id > 0)
    .sort((left, right) => left - right);

const invalidOptionsError = (): Error & { code: string } => {
  const error = new Error("INBOUND_OPTIONS_INVALID") as Error & { code: string };
  error.code = "INBOUND_OPTIONS_INVALID";
  return error;
};

export function useInboundOptions(
  authenticatedFetch: AuthenticatedFetch,
) {
  const [options, setOptions] = useState<Map<number, InboundVariantOptions>>(
    () => new Map(),
  );
  const [asOfDate, setAsOfDate] = useState<string | null>(null);

  const optionsRef = useRef(options);
  const asOfDateRef = useRef(asOfDate);
  const inFlightByVariant = useRef(
    new Map<number, Promise<InboundOptionsResponse>>(),
  );

  const mergeResponse = useCallback((response: InboundOptionsResponse) => {
    const next = new Map(optionsRef.current);
    for (const item of response.items) {
      next.set(item.product_variant_id, item);
    }
    optionsRef.current = next;
    asOfDateRef.current = response.as_of_date;
    setOptions(next);
    setAsOfDate(response.as_of_date);
  }, []);

  const ensure = useCallback(
    async (requestedIds: number[]): Promise<ReadyInboundOptions> => {
      const ids = normalizeIds(requestedIds);
      const waits = new Set<Promise<InboundOptionsResponse>>();
      const missing: number[] = [];

      for (const id of ids) {
        if (optionsRef.current.has(id)) continue;
        const inFlight = inFlightByVariant.current.get(id);
        if (inFlight) waits.add(inFlight);
        else missing.push(id);
      }

      if (missing.length) {
        const request = authenticatedFetch("/warehouse/inbound/options", {
          method: "POST",
          body: JSON.stringify({ ids: missing }),
        })
          .then(parseInboundOptions)
          .then((response) => {
            mergeResponse(response);
            return response;
          })
          .finally(() => {
            for (const id of missing) {
              inFlightByVariant.current.delete(id);
            }
          });

        for (const id of missing) {
          inFlightByVariant.current.set(id, request);
        }
        waits.add(request);
      }

      if (waits.size) {
        await Promise.all(waits);
      }

      const ready = optionsRef.current;
      const currentAsOfDate = asOfDateRef.current;
      if (
        ids.some((id) => !ready.has(id)) ||
        !currentAsOfDate
      ) {
        throw invalidOptionsError();
      }

      return {
        options: new Map(ready),
        asOfDate: currentAsOfDate,
      };
    },
    [authenticatedFetch, mergeResponse],
  );

  const preload = useCallback(
    (ids: number[]) => {
      void ensure(ids).catch(() => {
        // Passive preparation is best-effort. Submit retries the same
        // authoritative request and reports only a real preparation failure.
      });
    },
    [ensure],
  );

  return {
    options,
    asOfDate,
    ensure,
    preload,
  };
}
