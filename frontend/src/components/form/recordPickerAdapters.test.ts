import { beforeEach, describe, expect, it, vi } from "vitest";

import { userRecordAdapter } from "@/components/form/recordPickerAdapters";
import { listUsers } from "@/features/users/api";
import type { UserRow } from "@/features/users/types";

vi.mock("@/features/users/api", () => ({
  listUsers: vi.fn(),
  getUser: vi.fn(),
}));

const signal = new AbortController().signal;

const ada: UserRow = {
  id: "user_ada",
  account: "ada",
  display_name: "Ada",
  email: null,
  locale: "en-US",
  display_timezone: null,
  role_id: null,
  role_key: null,
  role_name: null,
  status: "active",
  identity_source: "local",
  last_login_at: null,
};

describe("record picker adapters", () => {
  beforeEach(() => {
    vi.mocked(listUsers).mockReset();
  });

  it("asks the server for one page of the identity source", async () => {
    vi.mocked(listUsers).mockResolvedValue({
      items: [ada],
      total: 1,
      limit: 20,
      offset: 0,
    });

    const options = await userRecordAdapter({ identitySource: "local" }).search(
      "ada",
      signal,
    );

    expect(listUsers).toHaveBeenCalledTimes(1);
    expect(listUsers).toHaveBeenCalledWith({
      q: "ada",
      identity_source: "local",
      limit: 20,
      offset: 0,
      signal,
    });
    expect(options).toEqual([{ id: "user_ada", name: "Ada", key: "ada" }]);
  });
});
