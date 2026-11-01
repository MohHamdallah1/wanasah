import { useCallback, useEffect, useRef, useState } from "react";

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

// The company calendar day can differ from the device calendar day.
export function companyLocalDate(timeZone: string, instant = new Date()): string | null {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(instant);
    const part = (type: string) => parts.find((item) => item.type === type)?.value;
    const year = part("year"), month = part("month"), day = part("day");
    return year && month && day ? [year, month, day].join("-") : null;
  } catch {
    return null;
  }
}

export function useInboundOptions(
  authenticatedFetch: AuthenticatedFetch,
  scopeKey: string,
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
  const generationRef = useRef(0);
  const cacheScopeRef = useRef(scopeKey);
  const [renderScope, setRenderScope] = useState(scopeKey);

  // Invalidate immediately on actor/company change, even before effects.
  if (cacheScopeRef.current !== scopeKey) {
    cacheScopeRef.current = scopeKey;
    ++generationRef.current;
    optionsRef.current = new Map();
    asOfDateRef.current = null;
    inFlightByVariant.current.clear();
  }
  useEffect(() => {
    if (renderScope !== scopeKey) {
      setOptions(new Map());
      setAsOfDate(null);
      setRenderScope(scopeKey);
    }
  }, [renderScope, scopeKey]);

  const invalidate = useCallback(() => {
    ++generationRef.current;
    optionsRef.current = new Map();
    asOfDateRef.current = null;
    inFlightByVariant.current.clear();
    setOptions(new Map());
    setAsOfDate(null);
  }, []);

  const mergeResponse = useCallback((response: InboundOptionsResponse) => {
    // Results sampled on different company dates must never share one map.
    if (asOfDateRef.current && response.as_of_date < asOfDateRef.current) {
      throw invalidOptionsError();
    }
    const next = asOfDateRef.current && response.as_of_date !== asOfDateRef.current
      ? new Map<number, InboundVariantOptions>()
      : new Map(optionsRef.current);
    for (const item of response.items) {
      next.set(item.product_variant_id, item);
    }
    optionsRef.current = next;
    asOfDateRef.current = response.as_of_date;
    setOptions(next);
    setAsOfDate(response.as_of_date);
    setRenderScope(scopeKey);
  }, [scopeKey]);

  const ensure = useCallback(
    async (requestedIds: number[]): Promise<ReadyInboundOptions> => {
      const ids = normalizeIds(requestedIds);
      const generation = generationRef.current;
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
            if (generation !== generationRef.current) throw invalidOptionsError();
            mergeResponse(response);
            return response;
          })
          .finally(() => {
            for (const id of missing) {
              if (inFlightByVariant.current.get(id) === request) {
                inFlightByVariant.current.delete(id);
              }
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
      if (generation !== generationRef.current) throw invalidOptionsError();

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

  // Always refresh before posting, and refresh visible hints on focus/date changes.
  const refresh = useCallback((ids: number[]) => {
    invalidate();
    return ensure(ids);
  }, [ensure, invalidate]);

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
    options: renderScope === scopeKey ? options : new Map<number, InboundVariantOptions>(),
    asOfDate: renderScope === scopeKey ? asOfDate : null,
    ensure,
    preload,
    refresh,
  };
}
