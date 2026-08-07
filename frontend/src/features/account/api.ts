import { apiClient } from "@/lib/api";
import type { CurrentUser } from "@/providers/session-store";

export type UpdateProfilePayload = {
  display_name?: string;
  email?: string | null;
  locale?: string;
};

export type ChangePasswordPayload = {
  current_password: string;
  new_password: string;
};

export async function patchAccountProfile(
  payload: UpdateProfilePayload,
): Promise<CurrentUser> {
  const data = await apiClient<{ user: CurrentUser }>("/account/profile", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  return data.user;
}

export async function changeAccountPassword(
  payload: ChangePasswordPayload,
): Promise<void> {
  await apiClient<{ success: boolean }>("/account/password", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}
