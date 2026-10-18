import { beforeEach, describe, expect, it, vi } from "vitest";

import { getBusinessDomain, listBusinessDomains } from "@/features/business-domains/api";
import type { BusinessDomain } from "@/features/business-domains/types";
import {
  businessDomainRecordAdapter,
  userRecordAdapter,
} from "@/components/form/recordPickerAdapters";
import { listUsers } from "@/features/users/api";
import type { UserRow } from "@/features/users/types";
import { Instant } from "@/lib/instant";

vi.mock("@/features/users/api", () => ({
  listUsers: vi.fn(),
  getUser: vi.fn(),
}));

vi.mock("@/features/business-domains/api", () => ({
  listBusinessDomains: vi.fn(),
  getBusinessDomain: vi.fn(),
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

const orders: BusinessDomain = {
  id: "dom_orders",
  code: "orders",
  name: "Orders",
  description: null,
  created_at: Instant.parse("2026-10-16T00:00:00Z"),
  updated_at: Instant.parse("2026-10-16T00:00:00Z"),
};

describe("record picker adapters", () => {
  beforeEach(() => {
    vi.mocked(listUsers).mockReset();
    vi.mocked(listBusinessDomains).mockReset();
    vi.mocked(getBusinessDomain).mockReset();
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

  it("resolves a business domain by id", async () => {
    vi.mocked(getBusinessDomain).mockResolvedValue({ domain: orders });

    const options = await businessDomainRecordAdapter().resolve(
      ["dom_orders"],
      signal,
    );

    expect(listBusinessDomains).not.toHaveBeenCalled();
    expect(getBusinessDomain).toHaveBeenCalledWith("dom_orders", { signal });
    expect(options).toEqual([{ id: "dom_orders", name: "Orders", key: "orders" }]);
  });
});
