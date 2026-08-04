import { apiClient } from "@/lib/api";
import type { NavigationResponse } from "@/features/console/types";

export function fetchConsoleNavigation() {
  return apiClient<NavigationResponse>("/console/navigation");
}
