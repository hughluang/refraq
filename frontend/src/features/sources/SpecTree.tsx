"use client";

import { ActionIcon, Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { FieldDisplay } from "@/components/form/FieldDisplay";
import { FormSection } from "@/components/form/FormSection";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { propertyType } from "./connectorFields";
import type { ConnectorSpec, JsonSchemaProperty, SourceAccess } from "./types";
import styles from "./SpecTree.module.css";

export { defaultsFromSchema, validateSourceAccess } from "./connectorFields";

type SpecTreeProps = {
  schema: ConnectorSpec | null;
  value: SourceAccess;
  onChange: (next: SourceAccess) => void;
  editable: boolean;
  errors?: Record<string, ReactNode>;
};

const CERTIFICATES = ["ssl_root_cert", "ssl_client_cert", "ssl_client_key"];
const AUTHENTICATION = ["username", "password"];

function fieldLabel(key: string, t: (key: string) => string) {
  if (["host", "port", "username"].includes(key)) return t(`sources.fields.${key}`);
  const translationKey = `sources.connection.${key}`;
  const label = t(translationKey);
  return label === translationKey ? key : label;
}

function tlsLabel(mode: string, t: (key: string) => string) {
  const key = `sources.connection.mode.${mode}`;
  const label = t(key);
  return label === key ? mode : label;
}

export function SpecTree({ schema, value, editable, onChange, errors = {} }: SpecTreeProps) {
  const t = useTranslate();
  const advanced = useRef<HTMLDetailsElement>(null);
  const firstError = Object.keys(errors).find((path) => errors[path]);
  useLayoutEffect(() => {
    const panel = advanced.current;
    if (!panel || !firstError) return;
    const input = Array.from(panel.querySelectorAll<HTMLElement>("[name]"))
      .find((element) => element.getAttribute("name") === firstError);
    if (input && !panel.open) {
      panel.open = true;
      input.focus();
    }
  }, [firstError]);

  if (!schema) return <Text size="sm" c="dimmed">{t("sources.spec.loading")}</Text>;
  const properties = schema.properties ?? {};
  const mode = String(value.ssl_mode ?? properties.ssl_mode?.default ?? "");
  const tls = properties.ssl_mode;
  const fixedTls = tls?.enum?.length === 1;
  const extraSpec = properties.extra;
  const supportsExtra = extraSpec && extraSpec.additionalProperties !== false;
  const options = value.extra && typeof value.extra === "object" && !Array.isArray(value.extra)
    ? value.extra as Record<string, string> : {};
  const optionCount = Object.keys(options).length;
  const setField = (key: string, next: unknown) => onChange({ ...value, [key]: next });

  const renderField = (key: string) => {
    const prop = properties[key];
    const current = value[key];
    const label = fieldLabel(key, t);
    const path = `access.${key}`;
    const shared = { label, name: path, editable, required: editable && schema.required?.includes(key), error: errors[path] };
    const secret = prop["x-secret"];
    if (secret && !editable) return <FieldDisplay key={key} label={label} value={t("sources.connection.hidden")} />;
    if (prop.enum) {
      const data = key === "ssl_mode" ? prop.enum.map((value) => ({ value, label: tlsLabel(value, t) })) : prop.enum;
      return <SelectField key={key} {...shared} editable={editable && prop.enum.length > 1}
        attributes={{ input: { name: path } }} hiddenInputProps={{ name: undefined }}
        data={data} value={typeof current === "string" ? current : null}
        onChange={(next) => { if (next != null) setField(key, next); }} />;
    }
    if (["integer", "number"].includes(propertyType(prop))) {
      return <NumberField key={key} {...shared} min={prop.minimum} max={prop.maximum}
        allowDecimal={propertyType(prop) === "number"} clampBehavior="none"
        value={typeof current === "number" || typeof current === "string" ? current : ""}
        onChange={(next) => setField(key, next)} />;
    }
    const text = typeof current === "string" ? current : "";
    if (CERTIFICATES.includes(key)) {
      return <TextareaField key={key} {...shared} autosize minRows={3} maxRows={8} spellCheck={false}
        autoComplete="off" value={text} onChange={(event) => setField(key, event.currentTarget.value)} />;
    }
    return <TextField key={key} {...shared} type={secret ? "password" : "text"} maxLength={prop.maxLength}
      autoComplete={secret ? "new-password" : "off"} value={text}
      onChange={(event) => setField(key, event.currentTarget.value)} />;
  };

  const endpoint = Object.keys(properties).filter((key) =>
    !AUTHENTICATION.includes(key) && !CERTIFICATES.includes(key)
      && key !== "ssl_mode" && propertyType(properties[key]) !== "object");
  const authentication = AUTHENTICATION.filter((key) => key in properties);
  const certificates = CERTIFICATES.filter((key) => key in properties && (mode !== "disable" || value[key]));
  const hasCertificate = certificates.some((key) => Boolean(value[key]));
  const hasAdvanced = (tls && !fixedTls) || certificates.length > 0 || (supportsExtra && (editable || optionCount > 0));
  return (
    <Stack gap="lg">
      {endpoint.length > 0 || fixedTls ? (
        <FormSection order={3} title={t("sources.connection.endpoint")}>
          {endpoint.map(renderField)}
          {fixedTls ? renderField("ssl_mode") : null}
        </FormSection>
      ) : null}
      {authentication.length > 0 ? (
        <FormSection order={3} title={t("sources.connection.authentication")}>
          {authentication.map(renderField)}
        </FormSection>
      ) : null}
      {hasAdvanced ? (
        <details key={schema.$id} className={styles.advanced} ref={advanced}>
          <summary>
            {t("sources.connection.advanced")}
            <Text component="span" size="xs" c="dimmed" ms="sm">
              {[tls && !fixedTls ? tlsLabel(mode, t) : null,
                hasCertificate ? t("sources.connection.certificateConfigured") : null,
                optionCount ? t("sources.connection.count", { count: optionCount }) : null].filter(Boolean).join(" · ")}
            </Text>
          </summary>
          <Stack p="md" gap="md">
            {(tls && !fixedTls) || certificates.length > 0 ? (
              <FormSection order={3} title={t("sources.connection.transport")}>
                {tls && !fixedTls ? renderField("ssl_mode") : null}
                {certificates.map(renderField)}
              </FormSection>
            ) : null}
            {supportsExtra && (editable || optionCount > 0) ? (
              <DriverOptions spec={extraSpec} options={options} editable={editable} errors={errors}
                onChange={(next) => setField("extra", next)} />
            ) : null}
          </Stack>
        </details>
      ) : null}
    </Stack>
  );
}

function DriverOptions({ spec, options, editable, errors, onChange }: {
  spec: JsonSchemaProperty;
  options: Record<string, string>;
  editable: boolean;
  errors: Record<string, ReactNode>;
  onChange: (options: Record<string, string>) => void;
}) {
  const t = useTranslate();
  const [draft, setDraft] = useState("");
  const name = draft.trim();
  const duplicate = Object.hasOwn(options, name);
  const add = () => {
    if (!name || duplicate) return;
    onChange({ ...options, [name]: "" });
    setDraft("");
  };
  return (
    <FormSection order={3} title={t("sources.connection.options")} columns={1}>
      {Object.entries(options).map(([key, value]) => (
        <Group key={key} align="flex-end" gap="xs" wrap="nowrap">
          <TextField editable={editable} label={key} name={`access.extra.${key}`} value={value}
            style={{ flex: 1, minWidth: 0 }} error={errors[`access.extra.${key}`]}
            maxLength={typeof spec.additionalProperties === "object" ? spec.additionalProperties.maxLength : undefined}
            onChange={(event) => onChange({ ...options, [key]: event.currentTarget.value })} />
          {editable ? <ActionIcon type="button" variant="subtle" color="red"
            aria-label={t("sources.connection.removeOption", { name: key })} onClick={() => {
              const next = { ...options };
              delete next[key];
              onChange(next);
            }}>×</ActionIcon> : null}
        </Group>
      ))}
      {editable ? (
        <Group align="flex-end" gap="xs">
          <TextField editable label={t("sources.connection.newOption")} style={{ flex: 1 }}
            maxLength={spec.propertyNames?.maxLength} value={draft}
            error={duplicate ? t("sources.connection.duplicate") : undefined}
            onChange={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") { event.preventDefault(); add(); }
            }} />
          <Button type="button" variant="default" disabled={!name || duplicate} onClick={add}>
            {t("sources.connection.addOption")}
          </Button>
        </Group>
      ) : null}
    </FormSection>
  );
}
