import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IconApps, IconLock } from "@tabler/icons-react";
import { describe, expect, it } from "vitest";

import { moduleIcon } from "@/components/icons";
import { GENERATED_MODULE_CATALOG } from "@/features/console/module-identity/generated-catalog";
import { permissionGroupId } from "@/features/roles/permissionGroups";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const COPY_KEYS = [
  "inboundCredentials.title",
  "inboundCredentials.description",
  "inboundCredentials.create",
  "inboundCredentials.createTitle",
  "inboundCredentials.createSubmit",
  "inboundCredentials.created",
  "inboundCredentials.saved",
  "inboundCredentials.deleteTitle",
  "inboundCredentials.deleteConsequence",
  "inboundCredentials.deleted",
  "inboundCredentials.search",
  "inboundCredentials.empty",
  "inboundCredentials.noMatch",
  "inboundCredentials.backToList",
  "inboundCredentials.actions.navigation",
  "inboundCredentials.actions.standard",
  "inboundCredentials.fields.name",
  "inboundCredentials.fields.type",
  "inboundCredentials.fields.secret",
  "inboundCredentials.fields.secretHint",
  "inboundCredentials.fields.secretKeep",
  "inboundCredentials.fields.secretSet",
  "inboundCredentials.fields.location",
  "inboundCredentials.fields.parameterName",
  "inboundCredentials.fields.parameterHint",
  "inboundCredentials.fields.signatureHeader",
  "inboundCredentials.fields.encoding",
  "inboundCredentials.fields.prefix",
  "inboundCredentials.fields.prefixHint",
  "inboundCredentials.fields.timestampHeader",
  "inboundCredentials.fields.timestampHint",
  "inboundCredentials.location.header",
  "inboundCredentials.location.query",
  "inboundCredentials.encoding.hex",
  "inboundCredentials.encoding.base64",
  "inboundCredentials.types.token",
  "inboundCredentials.types.hmac_sha256",
  "inboundCredentials.list.type",
  "inboundCredentials.validation.name",
  "inboundCredentials.validation.secret",
  "inboundCredentials.validation.parameterName",
  "inboundCredentials.validation.signatureHeader",
  "inboundCredentials.picker.placeholder",
  "inboundCredentials.picker.missing",
  "inboundCredentials.picker.loadFailed",
  "problems.INBOUND_CREDENTIAL_NOT_FOUND",
  "problems.INBOUND_CREDENTIAL_IN_USE",
] as const;

describe("inbound credential module", () => {
  it("registers the record routes beside HTTP Accounts", () => {
    const ids = GENERATED_MODULE_CATALOG.map((module) => module.id);
    expect(ids.indexOf("inbound-credentials")).toBe(ids.indexOf("http-accounts") + 1);
    const inbound = GENERATED_MODULE_CATALOG.find((module) => module.id === "inbound-credentials");
    expect(inbound?.label_key).toBe("inboundCredentials.title");
    expect(inbound?.icon).toBe("lock");
    expect(inbound?.routes).toEqual({
      list: "/console/inbound-credentials",
      create: "/console/inbound-credentials/new",
      edit: "/console/inbound-credentials/:id/edit",
      show: "/console/inbound-credentials/:id",
      aliases: [],
    });
    expect(inbound?.actions).toEqual({
      list: "inbound_credential:read",
      create: "inbound_credential:write",
      edit: "inbound_credential:write",
      delete: "inbound_credential:write",
      show: "inbound_credential:read",
      sample: null,
    });
  });

  it("groups the credential permissions on that module", () => {
    expect(permissionGroupId("http_account:read", GENERATED_MODULE_CATALOG)).toBe("http-accounts");
    expect(permissionGroupId("inbound_credential:read", GENERATED_MODULE_CATALOG)).toBe(
      "inbound-credentials",
    );
    expect(permissionGroupId("inbound_credential:write", GENERATED_MODULE_CATALOG)).toBe(
      "inbound-credentials",
    );
  });

  it("resolves the lock icon instead of the apps fallback", () => {
    const rendered = renderToStaticMarkup(createElement(moduleIcon("lock")));
    const lock = renderToStaticMarkup(createElement(IconLock, { size: 16, stroke: 1.5 }));
    const apps = renderToStaticMarkup(createElement(IconApps, { size: 16, stroke: 1.5 }));
    expect(rendered).toBe(lock);
    expect(rendered).not.toBe(apps);
  });

  it("has English and Chinese operator copy", () => {
    const english = en as Record<string, string>;
    const chinese = zh as Record<string, string>;
    for (const key of COPY_KEYS) {
      expect(english[key], key).toEqual(expect.any(String));
      expect(chinese[key], key).toEqual(expect.any(String));
      expect(english[key].length, key).toBeGreaterThan(0);
      expect(chinese[key].length, key).toBeGreaterThan(0);
      expect(english[key], key).not.toBe(key);
      expect(chinese[key], key).not.toBe(key);
    }
  });
});
