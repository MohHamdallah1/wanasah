import {
  parseRepresentative,
  parseRepresentativeList,
  type CreateRepresentativeInput,
  type Representative,
  type RepresentativeAuthFetch,
  type RepresentativeListResult,
  type RepresentativeStatusFilter,
  type UpdateRepresentativeInput,
} from "./contracts";

const jsonRequest = (method: string, value: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

export async function listRepresentatives(
  authFetch: RepresentativeAuthFetch,
  options: {
    search: string;
    status: RepresentativeStatusFilter;
    cursor?: string | null;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<RepresentativeListResult> {
  const params = new URLSearchParams();
  if (options.search.length >= 2) params.set("search", options.search);
  if (options.status !== "all") {
    params.set("active", String(options.status === "active"));
  }
  if (options.cursor) params.set("cursor", options.cursor);
  params.set("limit", String(options.limit ?? 30));

  return parseRepresentativeList(
    await authFetch(`/representatives?${params.toString()}`, { signal: options.signal }),
  );
}

export async function getRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  signal?: AbortSignal,
): Promise<Representative> {
  return parseRepresentative(
    await authFetch(`/representatives/${representativeId}`, { signal }),
  );
}

export async function createRepresentative(
  authFetch: RepresentativeAuthFetch,
  input: CreateRepresentativeInput,
  requestId: string,
): Promise<Representative> {
  return parseRepresentative(
    await authFetch(
      "/representatives",
      jsonRequest("POST", { request_id: requestId, ...input }),
    ),
  );
}

export async function updateRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  input: UpdateRepresentativeInput,
  requestId: string,
): Promise<Representative> {
  return parseRepresentative(
    await authFetch(
      `/representatives/${representativeId}`,
      jsonRequest("PATCH", { request_id: requestId, ...input }),
    ),
  );
}

export async function deactivateRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  requestId: string,
): Promise<void> {
  await authFetch(
    `/representatives/${representativeId}/deactivate`,
    jsonRequest("POST", { request_id: requestId }),
  );
}

export async function reactivateRepresentative(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  requestId: string,
): Promise<void> {
  await authFetch(
    `/representatives/${representativeId}/reactivate`,
    jsonRequest("POST", { request_id: requestId }),
  );
}

export async function resetRepresentativeCredentials(
  authFetch: RepresentativeAuthFetch,
  representativeId: number,
  newPassword: string,
  requestId: string,
): Promise<void> {
  await authFetch(
    `/representatives/${representativeId}/credentials/reset`,
    jsonRequest("POST", {
      request_id: requestId,
      new_password: newPassword,
    }),
  );
}
