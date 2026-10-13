import {
  parseRepresentativeList,
  parseRepresentativeResponse,
  type CreateRepresentativeInput,
  type Representative,
  type RepresentativeAuthFetch,
  type RepresentativeListResult,
  type RepresentativeStatusFilter,
  type UpdateRepresentativeInput,
} from "./contracts";

const jsonBody = (value: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

export async function listRepresentatives(
  authFetch: RepresentativeAuthFetch,
  options: {
    search: string;
    status: RepresentativeStatusFilter;
    signal?: AbortSignal;
  },
): Promise<RepresentativeListResult> {
  const params = new URLSearchParams();
  if (options.search) params.set("search", options.search);
  if (options.status !== "all") {
    params.set("active", String(options.status === "active"));
  }
  const suffix = params.size ? `?${params.toString()}` : "";
  return parseRepresentativeList(
    await authFetch(`/representatives${suffix}`, { signal: options.signal }),
  );
}

export async function getRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  signal?: AbortSignal,
): Promise<Representative> {
  return parseRepresentativeResponse(
    await authFetch(`/representatives/${representativeId}`, { signal }),
  );
}

export async function createRepresentative(
  authFetch: RepresentativeAuthFetch,
  input: CreateRepresentativeInput,
): Promise<Representative> {
  return parseRepresentativeResponse(
    await authFetch("/representatives", {
      method: "POST",
      ...jsonBody(input),
    }),
  );
}

export async function updateRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  input: UpdateRepresentativeInput,
): Promise<Representative> {
  return parseRepresentativeResponse(
    await authFetch(`/representatives/${representativeId}`, {
      method: "PATCH",
      ...jsonBody(input),
    }),
  );
}

export async function deactivateRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
): Promise<void> {
  await authFetch(`/representatives/${representativeId}/deactivate`, {
    method: "POST",
  });
}

export async function reactivateRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
): Promise<void> {
  await authFetch(`/representatives/${representativeId}/reactivate`, {
    method: "POST",
  });
}

/**
 * The frozen plan defines a dedicated reset endpoint and says its response must
 * contain metadata only, but it does not freeze an operator-supplied request
 * field. Until that contract exists, send no invented credential field.
 */
export async function resetRepresentativeCredentials(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
): Promise<void> {
  await authFetch(`/representatives/${representativeId}/credentials/reset`, {
    method: "POST",
  });
}
