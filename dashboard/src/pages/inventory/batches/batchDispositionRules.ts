import type { BatchDisposition } from "./contracts";

const transitions: Record<
  BatchDisposition,
  readonly BatchDisposition[]
> = {
  RELEASED: [
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
  ],
  QUARANTINED: [
    "RELEASED",
    "BLOCKED",
    "RECALLED",
  ],
  BLOCKED: ["RECALLED"],
  RECALLED: [],
};

export function allowedBatchDispositionTargets(
  current: BatchDisposition,
): readonly BatchDisposition[] {
  return transitions[current];
}
