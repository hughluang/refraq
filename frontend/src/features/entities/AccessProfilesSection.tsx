"use client";

import {
  Button,
  Collapse,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import {
  copyProfile,
  createProfile,
  deleteProfile,
  getAccessSummary,
  patchProfile,
} from "@/features/entities/accessApi";
import {
  accessKeyFromName,
  columnsFromMatrix,
  isAccessKey,
  levelModeKind,
  levelOptionLabel,
  matrixFromProfiles,
  profileGrantCount,
  profileIsAllClear,
  sameProfileColumns,
} from "@/features/entities/accessLogic";
import { accessProblemText } from "@/features/entities/accessProblem";
import type { AccessOption, AccessRun } from "@/features/entities/accessSession";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { RecordPicker } from "@/components/form/RecordPicker";
import { entityRecordAdapter } from "@/components/form/recordPickerAdapters";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { localListSession } from "@/lib/list-state";

type Props = {
  entityId: string;
  summary: AccessSummary | null;
  busyId: string | null;
  run: AccessRun;
  onOptionsError: (message: string) => void;
  loading?: boolean;
  error?: string | null;
  onReload?: () => void | Promise<void>;
};

export function AccessProfilesSection({
  entityId,
  summary,
  busyId,
  run,
  onOptionsError,
  loading = false,
  error = null,
  onReload,
}: Props) {
  const t = useTranslate();
  const [profileKey, setProfileKey] = useState("");
  const [profileName, setProfileName] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [identifierOpen, setIdentifierOpen] = useState(false);
  const [matrix, setMatrix] = useState<Record<string, Record<string, string>>>({});
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyEntity, setCopyEntity] = useState<string | null>(null);
  const [copyProfiles, setCopyProfiles] = useState<AccessOption[]>([]);
  const [copyProfileId, setCopyProfileId] = useState<string | null>(null);
  const [copyKey, setCopyKey] = useState("");
  const [copyName, setCopyName] = useState("");

  const ladders = summary?.ladders ?? [];
  const profiles = summary?.profiles ?? [];

  useEffect(() => {
    if (!summary) return;
    setMatrix(matrixFromProfiles(summary.ladders, summary.profiles));
  }, [summary]);

  const attributeIds = ladders.map((ladder) => ladder.attribute_id);
  const creating = busyId === "profile-create";
  const copying = busyId === "profile-copy";
  const derivedKey = accessKeyFromName(profileName);
  const effectiveKey = keyTouched ? profileKey : derivedKey;
  const showIdentifier =
    identifierOpen || (profileName.trim().length > 0 && !isAccessKey(effectiveKey));

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("entities.access.profiles")}
        description={t("entities.access.profiles.description")}
      />
      <ListTable
        embedded
        list={localListSession({
          total: ladders.length > 0 && profiles.length > 0 ? ladders.length : 0,
          loading,
          error,
          reload: onReload,
        })}
        columnCount={profiles.length > 0 && ladders.length > 0 ? 1 + profiles.length : 1}
        minWidth={640}
        emptyMessage={
          ladders.length === 0
            ? t("entities.access.profiles.needAttributes")
            : t("entities.access.profiles.empty")
        }
        head={
          <Table.Tr>
            <Table.Th>{t("entities.access.profiles.column")}</Table.Th>
            {ladders.length > 0
              ? profiles.map((profile) => {
                  const grantCount = profileGrantCount(profile.id, summary?.grants ?? []);
                  const allClear = profileIsAllClear(profile.columns, attributeIds);
                  return (
                    <Table.Th key={profile.id}>
                      <Stack gap={2}>
                        <RecordReference name={profile.name} recordKey={profile.key} />
                        {allClear ? (
                          <Text size="xs" c="dimmed">
                            {t("entities.access.summary.allClear")}
                          </Text>
                        ) : null}
                        <Text size="xs" c={grantCount === 0 ? "orange" : "dimmed"}>
                          {grantCount === 0
                            ? t("entities.access.profiles.notEffective")
                            : t("entities.access.profiles.grantCount", { count: grantCount })}
                        </Text>
                      </Stack>
                    </Table.Th>
                  );
                })
              : null}
          </Table.Tr>
        }
      >
        {ladders.map((ladder) => (
          <Table.Tr key={ladder.attribute_id}>
            <Table.Td>
              <RecordReference
                name={ladder.attribute_name}
                recordKey={ladder.type}
                copyable={false}
              />
            </Table.Td>
            {profiles.map((profile) => (
              <Table.Td key={profile.id}>
                <Select
                  aria-label={`${profile.name} ${ladder.attribute_name}`}
                  data={[
                    { value: "", label: t("entities.access.profiles.notInProfile") },
                    ...ladder.levels.map((level) => ({
                      value: level.key,
                      label: levelOptionLabel(
                        t(`entities.access.mask.${levelModeKind(level.mode)}`),
                        level.key,
                      ),
                    })),
                  ]}
                  value={matrix[profile.id]?.[ladder.attribute_id] ?? ""}
                  onChange={(value) =>
                    setMatrix((current) => ({
                      ...current,
                      [profile.id]: {
                        ...(current[profile.id] ?? {}),
                        [ladder.attribute_id]: value ?? "",
                      },
                    }))
                  }
                />
              </Table.Td>
            ))}
          </Table.Tr>
        ))}
        <Table.Tr>
          <Table.Td />
          {profiles.map((profile) => {
            const saving = busyId === `profile-save:${profile.id}`;
            const dirty = !sameProfileColumns(
              attributeIds,
              profile.columns,
              matrix[profile.id] ?? {},
            );
            return (
              <Table.Td key={profile.id}>
                <Group wrap="nowrap">
                  <Button
                    size="xs"
                    loading={saving}
                    disabled={!dirty || (busyId !== null && !saving)}
                    onClick={() =>
                      void run(`profile-save:${profile.id}`, "entities.access.saved.profiles", () =>
                        patchProfile(entityId, profile.id, {
                          columns: columnsFromMatrix(attributeIds, matrix[profile.id] ?? {}),
                        }).then(() => undefined),
                      )
                    }
                  >
                    {t("entities.access.profiles.save")}
                  </Button>
                  <RowActions
                    recordName={profile.name}
                    verbs={[
                      {
                        key: "delete",
                        label: t("entities.access.profiles.delete"),
                        color: "red",
                        disabledReason: busyId !== null ? t("common.loading") : undefined,
                        action: {
                          safety: "confirm",
                          recordName: profile.name,
                          title: t("entities.access.profiles.deleteTitle"),
                          consequence: t("entities.access.profiles.deleteBody", {
                            name: profile.name,
                          }),
                          confirmLabel: t("entities.access.profiles.delete"),
                          confirmColor: "red",
                          outcome: t("entities.access.saved.profileRemoved"),
                          execute: () => deleteProfile(entityId, profile.id),
                          onSuccess: onReload,
                        },
                      },
                    ]}
                  />
                </Group>
              </Table.Td>
            );
          })}
        </Table.Tr>
      </ListTable>
      <Group align="flex-end">
        <TextInput
          label={t("entities.access.profiles.name")}
          value={profileName}
          onChange={(event) => setProfileName(event.currentTarget.value)}
        />
        <Button
          loading={creating}
          disabled={
            !isAccessKey(effectiveKey) ||
            profileName.trim().length === 0 ||
            (busyId !== null && !creating)
          }
          onClick={() =>
            void run("profile-create", "entities.access.saved.profiles", async () => {
              await createProfile(entityId, {
                key: effectiveKey,
                name: profileName.trim(),
                columns: [],
              });
              setProfileKey("");
              setProfileName("");
              setKeyTouched(false);
              setIdentifierOpen(false);
            })
          }
        >
          {t("entities.access.profiles.create")}
        </Button>
      </Group>
      <Button
        size="sm"
        variant="subtle"
        w="fit-content"
        onClick={() => setIdentifierOpen((open) => !open)}
      >
        {identifierOpen ? t("entities.access.collapse") : t("entities.access.profiles.identifier")}
      </Button>
      <Collapse expanded={showIdentifier}>
        <TextInput
          label={t("entities.access.profiles.key")}
          description={t("entities.access.ladders.keyHint")}
          value={effectiveKey}
          onChange={(event) => {
            setKeyTouched(true);
            setProfileKey(event.currentTarget.value);
          }}
        />
      </Collapse>
      <Button size="sm" variant="default" w="fit-content" onClick={() => setCopyOpen((open) => !open)}>
        {copyOpen ? t("entities.access.collapse") : t("entities.access.profiles.copy")}
      </Button>
      <Collapse expanded={copyOpen}>
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            {t("entities.access.profiles.copyDescription")}
          </Text>
          <Group align="flex-end">
            <RecordPicker
              editable
              label={t("entities.access.profiles.copySource")}
              adapter={entityRecordAdapter()}
              excludeIds={[entityId]}
              value={copyEntity}
              onChange={(value) => {
                setCopyEntity(value);
                setCopyProfileId(null);
                setCopyProfiles([]);
                if (!value) return;
                void getAccessSummary(value)
                  .then((source) =>
                    setCopyProfiles(
                      source.profiles.map((profile) => ({
                        value: profile.id,
                        label: profile.name,
                      })),
                    ),
                  )
                  .catch((err: unknown) => onOptionsError(accessProblemText(err, t)));
              }}
            />
            <Select
              label={t("entities.access.profiles.copyScheme")}
              data={copyProfiles}
              value={copyProfileId}
              onChange={setCopyProfileId}
              placeholder={copyProfiles.length === 0 ? t("entities.access.profiles.copyEmpty") : undefined}
            />
            <TextInput
              label={t("entities.access.profiles.key")}
              description={t("entities.access.ladders.keyHint")}
              value={copyKey}
              onChange={(event) => setCopyKey(event.currentTarget.value)}
            />
            <TextInput
              label={t("entities.access.profiles.name")}
              value={copyName}
              onChange={(event) => setCopyName(event.currentTarget.value)}
            />
            <Button
              loading={copying}
              disabled={
                !copyEntity ||
                !copyProfileId ||
                !isAccessKey(copyKey.trim()) ||
                copyName.trim().length === 0 ||
                (busyId !== null && !copying)
              }
              onClick={() =>
                void run("profile-copy", "entities.access.saved.copied", async () => {
                  await copyProfile(entityId, {
                    source_entity_id: copyEntity as string,
                    source_profile_id: copyProfileId as string,
                    key: copyKey.trim(),
                    name: copyName.trim(),
                  });
                  setCopyKey("");
                  setCopyName("");
                })
              }
            >
              {t("entities.access.profiles.copyAction")}
            </Button>
          </Group>
        </Stack>
      </Collapse>
    </Stack>
  );
}
