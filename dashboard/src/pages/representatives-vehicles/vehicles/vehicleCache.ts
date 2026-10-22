import type { InfiniteData } from "@tanstack/react-query";
import type { Vehicle, VehicleListResult } from "./contracts";

export function replaceVehicleInInfiniteData(
  cached: InfiniteData<VehicleListResult> | undefined,
  updated: Vehicle,
): InfiniteData<VehicleListResult> | undefined {
  if (!cached) return cached;
  return {
    ...cached,
    pages: cached.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => item.id === updated.id ? updated : item),
    })),
  };
}
