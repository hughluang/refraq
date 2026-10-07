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
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { EmptyState } from "@/components/feedback/EmptyState";
import { SectionHeader } from "@/components/layout/SectionHeader";

type Props = {
  entityId: string;
  summary: AccessSummary;
  entities: AccessOption[];
  busyId: string | null;
  run: AccessRun;
  onOptionsError: (message: string) => void;
};

export function AccessProfilesSection({
  entityId,
  summary,
  entities,
  busyId,
  run,
  onOptionsError,
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
  const [deleteId, setDeleteId] = useState<string | null>(null);

  useEffect(() => {
    setMatrix(matrixFromProfiles(summary.ladders, summary.profiles));
  }, [summary]);

  const attributeIds = summary.ladders.map((ladder) => ladder.attribute_id);
  const deleting = summary.profiles.find((profile) => profile.id === deleteId) ?? null;
  const deleteBusy = deleteId != null && busyId === `profile-delete:${deleteId}`;
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
      {summary.ladders.length === 0 ? (
        <EmptyState message={t("entities.access.profiles.needAttributes")} />
      ) : summary.profiles.length === 0 ? (
        <EmptyState message={t("entities.access.profiles.empty")} />
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("entities.access.profiles.column")}</Table.Th>
                {summary.profiles.map((profile) => {
                  const grantCount = profileGrantCount(profile.id, summary.grants);
                  const allClear = profileIsAllClear(profile.columns, attributeIds);
                  return (
                    <Table.Th key={profile.id}>
                      <Stack gap={2}>
                        <Text fw={600}>{profile.name}</Text>
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
                })}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {summary.ladders.map((ladder) => (
                <Table.Tr key={ladder.attribute_id}>
                  <Table.Td>{ladder.attribute_name}</Table.Td>
                  {summary.profiles.map((profile) => (
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
                {summary.profiles.map((profile) => {
                  const saving = busyId === `profile-save:${profile.id}`;
                  const dirty = !sameProfileColumns(
                    attributeIds,
                    profile.columns,
                    matrix[profile.id] ?? {},
                  );
                  return (
                    <Table.Td key={profile.id}>
                      <Group>
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
                        <Button
                          size="xs"
                          color="red"
                          variant="light"
                          disabled={busyId !== null}
                          onClick={() => setDeleteId(profile.id)}
                        >
                          {t("entities.access.profiles.delete")}
                        </Button>
                      </Group>
                    </Table.Td>
                  );
                })}
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
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
            <Select
              label={t("entities.access.profiles.copySource")}
              data={entities}
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
      <ConfirmActionModal
        opened={deleting !== null}
        onClose={() => setDeleteId(null)}
        title={t("entities.access.profiles.deleteTitle")}
        body={t("entities.access.profiles.deleteBody", { name: deleting?.name ?? "" })}
        confirmLabel={t("entities.access.profiles.delete")}
        confirmColor="red"
        loading={deleteBusy}
        onConfirm={() => {
          if (!deleteId) return;
          void run(`profile-delete:${deleteId}`, "entities.access.saved.profileRemoved", () =>
            deleteProfile(entityId, deleteId),
          ).then((ok) => {
            if (ok) setDeleteId(null);
          });
        }}
      />
    </Stack>
  );
}
