"use client";

import {
  ActionIcon,
  Box,
  Button,
  Group,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useMemo, useState } from "react";

import type {
  ConnectorSpec,
  JsonSchemaProperty,
  SourceAccess,
} from "@/features/sources/types";

type SpecTreeProps = {
  schema: ConnectorSpec | null;
  value: SourceAccess;
  onChange: (next: SourceAccess) => void;
  disabled?: boolean;
};

function isSecret(prop: JsonSchemaProperty | undefined): boolean {
  return prop?.["x-secret"] === true;
}

function propType(prop: JsonSchemaProperty | undefined): string {
  const t = prop?.type;
  if (Array.isArray(t)) return t[0] ?? "string";
  return t ?? "string";
}

function defaultFromProp(key: string, prop: JsonSchemaProperty): unknown {
  if (key === "password") return "";
  if (prop.default !== undefined) return prop.default;
  if (propType(prop) === "object") return {};
  if (propType(prop) === "integer" || propType(prop) === "number") return 0;
  if (prop.enum?.length) return prop.enum[0];
  return "";
}

export function defaultsFromSchema(schema: ConnectorSpec): SourceAccess {
  const out: SourceAccess = {};
  const props = schema.properties ?? {};
  for (const [key, prop] of Object.entries(props)) {
    out[key] = defaultFromProp(key, prop);
  }
  return out;
}

export function SpecTree({ schema, value, onChange, disabled }: SpecTreeProps) {
  const t = useTranslate();
  const [extraOpen, setExtraOpen] = useState(true);
  const [newExtraKey, setNewExtraKey] = useState("");

  const required = useMemo(
    () => new Set(schema?.required ?? []),
    [schema?.required],
  );
  const properties = schema?.properties ?? {};

  if (!schema) {
    return (
      <Text size="sm" c="dimmed">
        {t("sources.spec.loading")}
      </Text>
    );
  }

  const setField = (key: string, next: unknown) => {
    onChange({ ...value, [key]: next });
  };

  const renderScalar = (key: string, prop: JsonSchemaProperty) => {
    const label = (
      <>
        {key}
        {required.has(key) ? (
          <Text span c="red" inherit>
            {" "}
            *
          </Text>
        ) : null}
      </>
    );
    const description = prop.description;
    const current = value[key];

    if (prop.enum?.length) {
      return (
        <Select
          key={key}
          label={label}
          description={description}
          data={prop.enum}
          value={typeof current === "string" ? current : (prop.default as string) ?? prop.enum[0]}
          disabled={disabled}
          onChange={(v) => setField(key, v ?? prop.enum![0])}
        />
      );
    }

    if (propType(prop) === "integer" || propType(prop) === "number") {
      return (
        <NumberInput
          key={key}
          label={label}
          description={description}
          min={prop.minimum}
          max={prop.maximum}
          allowDecimal={propType(prop) === "number"}
          disabled={disabled}
          value={typeof current === "number" ? current : undefined}
          onChange={(v) => setField(key, typeof v === "number" ? v : Number(v) || 0)}
        />
      );
    }

    if (isSecret(prop) || key === "password") {
      return (
        <TextInput
          key={key}
          label={label}
          description={description}
          type="password"
          autoComplete="new-password"
          disabled={disabled}
          value={typeof current === "string" ? current : ""}
          onChange={(e) => setField(key, e.currentTarget.value)}
        />
      );
    }

    if (
      key === "ssl_root_cert" ||
      key === "ssl_client_cert" ||
      key === "ssl_client_key"
    ) {
      return (
        <Textarea
          key={key}
          label={label}
          description={description}
          autosize
          minRows={2}
          disabled={disabled}
          value={typeof current === "string" ? current : ""}
          onChange={(e) => setField(key, e.currentTarget.value)}
        />
      );
    }

    return (
      <TextInput
        key={key}
        label={label}
        description={description}
        disabled={disabled}
        value={typeof current === "string" ? current : String(current ?? "")}
        onChange={(e) => setField(key, e.currentTarget.value)}
      />
    );
  };

  const sslMode = String(value.ssl_mode ?? "require");
  const showVerifyCerts =
    sslMode === "verify-ca" || sslMode === "verify-full";

  const extraProp = properties.extra;
  const extraValue =
    value.extra && typeof value.extra === "object" && !Array.isArray(value.extra)
      ? (value.extra as Record<string, string>)
      : {};

  const setExtra = (next: Record<string, string>) => {
    setField("extra", next);
  };

  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>
        {t("sources.spec.section")}
      </Text>
      {schema.$id ? (
        <Text size="xs" c="dimmed" ff="monospace">
          {schema.$id}
        </Text>
      ) : null}

      {Object.entries(properties).map(([key, prop]) => {
        if (key === "extra") return null;
        if (propType(prop) === "object") return null;
        const certKeys = new Set([
          "ssl_root_cert",
          "ssl_client_cert",
          "ssl_client_key",
        ]);
        if (certKeys.has(key) && !showVerifyCerts && !value[key]) {
          return null;
        }
        return renderScalar(key, prop);
      })}

      {extraProp ? (
        <Box
          p="sm"
          style={{
            border: "1px solid var(--mantine-color-gray-3)",
            borderRadius: 8,
          }}
        >
          <Group justify="space-between" mb="xs">
            <div>
              <Text size="sm" fw={600}>
                extra
              </Text>
              {extraProp.description ? (
                <Text size="xs" c="dimmed">
                  {extraProp.description}
                </Text>
              ) : null}
            </div>
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={() => setExtraOpen((o) => !o)}
            >
              {extraOpen ? "▼" : "▶"}
            </Button>
          </Group>
          {extraOpen ? (
            <Stack gap="xs">
              {Object.entries(extraValue).map(([ek, ev]) => (
                <Group key={ek} align="flex-end" wrap="nowrap" gap="xs">
                  <TextInput
                    label={ek}
                    style={{ flex: 1 }}
                    disabled={disabled}
                    value={ev}
                    onChange={(e) =>
                      setExtra({ ...extraValue, [ek]: e.currentTarget.value })
                    }
                  />
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    disabled={disabled}
                    onClick={() => {
                      const next = { ...extraValue };
                      delete next[ek];
                      setExtra(next);
                    }}
                    aria-label={t("sources.spec.removeExtra")}
                  >
                    ×
                  </ActionIcon>
                </Group>
              ))}
              <Group align="flex-end" gap="xs">
                <TextInput
                  label={t("sources.spec.addExtraKey")}
                  style={{ flex: 1 }}
                  disabled={disabled}
                  value={newExtraKey}
                  onChange={(e) => setNewExtraKey(e.currentTarget.value)}
                />
                <Button
                  variant="light"
                  disabled={disabled || !newExtraKey.trim()}
                  onClick={() => {
                    const k = newExtraKey.trim();
                    if (!k || k in extraValue) return;
                    setExtra({ ...extraValue, [k]: "" });
                    setNewExtraKey("");
                  }}
                >
                  {t("sources.spec.addExtra")}
                </Button>
              </Group>
            </Stack>
          ) : null}
        </Box>
      ) : null}
    </Stack>
  );
}
