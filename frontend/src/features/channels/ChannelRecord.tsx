"use client";

import {
  Box,
  Button,
  Drawer,
  Group,
  Modal,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import {
  suppressLeaveGuard,
  useLeaveGuardRegistration,
} from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { FormDialog } from "@/components/form/FormDialog";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { JobReference } from "@/components/display/JobReference";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StaleNotice } from "@/components/display/StaleNotice";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive, presentJobStatus } from "@/components/display/statusTone";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { AdjustmentsIcon, ListIcon, VersionsIcon } from "@/components/icons";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { FillColumn } from "@/components/layout/FillColumn";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  activateChannel,
  createChannel,
  deactivateChannel,
  deleteChannel,
  getChannel,
  getDraft,
  getRun,
  getVersion,
  listChannels,
  listNodeTypes,
  listRuns,
  patchChannel,
  previewPublish,
  previewTemplate,
  publishChannel,
  saveDraft,
  startRun,
  validateDraft,
  type DraftValidation,
} from "@/features/channels/api";
import { ChannelCanvas } from "@/features/channels/ChannelCanvas";
import { isTerminalRun, recordedKey } from "@/features/channels/runSession";
import type { ChannelTemplatePreview } from "@/features/channels/TemplateRunPreview";
import { ChannelRuns } from "@/features/channels/ChannelRuns";
import { ChannelVersions } from "@/features/channels/ChannelVersions";
import type { ExpressionContext, Graph, GraphProblem, RefinedPort } from "@/features/channels/types";
import {
  graphWithoutUnsetIntegers,
  validationContentKey,
  validationDelay,
  refusedProblems,
  validationResultApplies,
} from "@/features/channels/graphValidation";
import { formatGraphProblem } from "@/features/channels/problemLabel";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

import type { Channel, ChannelRunDetail, Confirmation, NodeTypeSpec } from "@/features/channels/types";
import { cancelJob } from "@/features/jobs/api";

const FORM_ID = "channel-record-form";
const NAME_MAX = 200;
const DESCRIPTION_MAX = 2000;

function runTimeoutSec(value: number | string): number | null {
  return typeof value === "number" && value > 0 ? Math.floor(value) : null;
}

function errorChannelOptions(
  options: { value: string; label: string }[],
  selected: string | null,
) {
  if (selected && !options.some((item) => item.value === selected)) {
    return [{ value: selected, label: selected }, ...options];
  }
  return options;
}

function runRetryLimit(value: number | string): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const next = Math.floor(value);
  if (next < 0 || next > 10) return null;
  return next;
}

type IdentityValues = {
  name: string;
  description: string;
  active: boolean;
};

class RecordInvalid extends Error {}

/** Save must reject while another page mutation holds the latch, so the form does not mark the draft saved. */
class PageMutationOccupied extends Error {}

type DraftAccess = "browse" | "edit" | "locked";

type Props =
  | { mode: "create" }
  | { mode: "show" | "edit"; channelId: string };

export function ChannelRecord(props: Props) {
  if (props.mode === "create") return <ChannelCreate />;
  return <ChannelExisting mode={props.mode} channelId={props.channelId} />;
}

function ChannelCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm({
    initialValues: { name: "", description: "" },
    onValuesChange: () => setSaveFailure(null),
  });

  return (
    <PageChrome
      title={t("channels.create.title")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button
                component={ConsoleLink}
                href="/console/channels"
                variant="default"
                size="sm"
              >
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
                  {t("channels.create.submit")}
                </Button>
              </HeaderAction>
            </>
          }
        />
      }
    >
      <form
        id={FORM_ID}
        onSubmit={form.onSubmit(async (values) => {
          try {
            const description = values.description.trim();
            const created = await createChannel({
              name: values.name.trim(),
              description: description ? description : null,
            });
            form.markSaved();
            suppressLeaveGuard();
            open?.({ type: "success", message: t("channels.create.success") });
            window.location.replace(`/console/channels/${created.channel.id}/edit`);
          } catch (error) {
            setSaveFailure(
              saveFailureFrom(
                t,
                error,
                form.applyApiError(error),
                t("channels.save.failed"),
              ),
            );
          }
        })}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <IdentityFields form={form} editable />
        </Stack>
      </form>
    </PageChrome>
  );
}

function ChannelExisting({
  mode,
  channelId,
}: {
  mode: "show" | "edit";
  channelId: string;
}) {
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const stopRunAction = useConsoleMutation();
  const deleteAction = useConsoleMutation();
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const { data: canJobs } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });
  const [channel, setChannel] = useState<Channel | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [baseline, setBaseline] = useState("");
  const [revision, setRevision] = useState(1);
  const [catalog, setCatalog] = useState<NodeTypeSpec[]>([]);
  const [problems, setProblems] = useState<GraphProblem[]>([]);
  const [ports, setPorts] = useState<RefinedPort[]>([]);
  const [expressionContext, setExpressionContext] = useState<ExpressionContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [panel, setPanel] = useState<"versions" | "runs" | null>(null);
  const [preview, setPreview] = useState<Confirmation | null>(null);
  const [publishJobId, setPublishJobId] = useState<string | null>(null);
  const [publishRevision, setPublishRevision] = useState(1);
  const [reloadToken, setReloadToken] = useState(0);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [runRequest, setRunRequest] = useState<{ stopAt: string | null } | null>(null);
  const [sessionRun, setSessionRun] = useState<ChannelRunDetail | null>(null);
  const [adoptToken, setAdoptToken] = useState(0);
  const nameEditorRef = useRef<ChannelNameHeadingHandle>(null);
  const form = useConsoleForm<IdentityValues>({
    initialValues: { name: "", description: "", active: false },
    onValuesChange: () => setSaveFailure(null),
    validate: {
      name: (value) => {
        const trimmed = value.trim();
        if (!trimmed) return t("channels.validation.name.required");
        if (trimmed.length > NAME_MAX) return t("channels.validation.name.length");
        return null;
      },
    },
  });
  const [errorChannels, setErrorChannels] = useState<{ value: string; label: string }[]>([]);
  const [errorChannelsFailed, setErrorChannelsFailed] = useState(false);
  const detailsForm = useConsoleForm<{
    description: string;
    timeout: number | string;
    retryLimit: number | string;
    errorChannelId: string | null;
  }>({
    initialValues: { description: "", timeout: "", retryLimit: "", errorChannelId: null },
  });
  const formRef = useRef(form);
  formRef.current = form;
  const validateSeq = useRef(0);
  const loadedChannelRef = useRef<string | null>(null);
  const arrivalRef = useRef(false);
  const runEpoch = useRef(0);
  const pageMutation = useRef(false);
  const [draftEpoch, setDraftEpoch] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    loadedChannelRef.current = null;
    validateSeq.current += 1;
    setProblems([]);
    setPorts([]);
    setExpressionContext(null);
    const epoch = ++runEpoch.current;
    setSessionRun(null);
    void listRuns(channelId, { target: "draft", limit: 1 })
      .then((page) => {
        const latest = page.items[0];
        if (!latest || cancelled || runEpoch.current !== epoch) return null;
        return getRun(channelId, latest.job_id);
      })
      .then((detail) => {
        if (!detail || cancelled || runEpoch.current !== epoch) return;
        setSessionRun(detail);
      })
      .catch((error: unknown) => {
        if (cancelled || runEpoch.current !== epoch) return;
        open?.({
          type: "error",
          message: problemMessage(t, error, t("channels.load.failed")),
        });
      });
    void Promise.all([getChannel(channelId), getDraft(channelId), listNodeTypes()])
      .then(([channelBody, draft, types]) => {
        if (cancelled) return;
        loadedChannelRef.current = channelId;
        arrivalRef.current = true;
        setChannel(channelBody.channel);
        setGraph(graphWithoutUnsetIntegers(draft.graph, types.items));
        setDraftEpoch((epoch) => epoch + 1);
        setBaseline(JSON.stringify(draft.graph));
        setRevision(draft.draft_revision);
        setCatalog(types.items);
        formRef.current.setValues({
          name: channelBody.channel.name,
          description: channelBody.channel.description ?? "",
          active: channelBody.channel.active,
        });
        formRef.current.markSaved();
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoadError(error instanceof ApiError ? error : null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, reloadToken]);

  useEffect(() => {
    if (mode !== "edit" || canWrite?.can !== false) return;
    suppressLeaveGuard();
    replace(`/console/channels/${channelId}`);
  }, [canWrite?.can, channelId, mode, replace]);

  const writable = mode === "edit" && Boolean(canWrite?.can);
  const runActive = sessionRun != null && !isTerminalRun(sessionRun.run.status);
  const draftAccess: DraftAccess = !writable ? "browse" : runActive ? "locked" : "edit";
  const draftEditable = draftAccess === "edit";
  const canStop = Boolean(canWrite?.can || canJobs?.can);
  const runJobId = sessionRun?.run.job_id ?? null;
  const runLive = useLiveStatus({
    enabled: Boolean(runJobId),
    key: runJobId,
    fetch: (signal) => getRun(channelId, runJobId ?? "", { signal }),
    isTerminal: (detail) => isTerminalRun(detail.run.status),
  });
  useEffect(() => {
    if (runLive.data) setSessionRun(runLive.data);
  }, [runLive.data]);
  const graphDirty = graph != null && JSON.stringify(graph) !== baseline;
  useLeaveGuardRegistration(writable && (form.isDirty() || graphDirty));

  const notifyError = (error: unknown) => {
    open?.({
      type: "error",
      message:
        error instanceof RecordInvalid
          ? error.message
          : problemMessage(t, error, t("channels.save.failed")),
    });
  };

  const graphRef = useRef(graph);
  graphRef.current = graph;
  const contentKey = graph ? validationContentKey(graph) : "";
  const scheduleRef = useRef({ content: "", delay: 0 });
  if (
    graph &&
    loadedChannelRef.current === channelId &&
    (arrivalRef.current || scheduleRef.current.content !== contentKey)
  ) {
    const opened = arrivalRef.current;
    arrivalRef.current = false;
    scheduleRef.current = {
      content: contentKey,
      delay: validationDelay(opened),
    };
  }

  useEffect(() => {
    const current = graphRef.current;
    if (canWrite?.can !== true || !current) return;
    if (loadedChannelRef.current !== channelId) return;
    const seq = ++validateSeq.current;
    const delay = scheduleRef.current.delay;
    const timer = window.setTimeout(() => {
      void validateDraft(channelId, current)
        .then((result) => {
          if (validateSeq.current !== seq) return;
          setProblems(result.problems);
          setPorts(result.ports);
          setExpressionContext(result.context);
        })
        .catch((error: unknown) => {
          if (validateSeq.current !== seq) return;
          notifyError(error);
        });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [canWrite?.can, channelId, contentKey, draftEpoch]);

  const reportBlockedGraph = (
    result: DraftValidation,
    source: Graph,
    blocking: GraphProblem[] = [],
  ) => {
    // A run or publish check can resolve after the canvas has moved on.
    // Applying that snapshot would replace the problems on screen and drop the newer check.
    if (!validationResultApplies(source, graphRef.current)) return;
    validateSeq.current += 1;
    setProblems(result.problems);
    setPorts(result.ports);
    setExpressionContext(result.context);
    setPanel(null);
    const firstError =
      blocking[0] ?? result.problems.find((problem) => problem.severity !== "warning");
    open?.({
      type: "error",
      message: firstError
        ? t("channels.validate.failedWith", {
            problem: formatGraphProblem(t, firstError, source),
          })
        : t("channels.validate.failed"),
    });
  };

  const revealInvalidGraph = (error: unknown) => {
    if (!(error instanceof ApiError) || error.code !== "CHANNEL_GRAPH_INVALID" || !graph) {
      return null;
    }
    setPreview(null);
    setRunRequest(null);
    const blocking = refusedProblems(error);
    return validateDraft(channelId, graph).then((result) =>
      reportBlockedGraph(result, graph, blocking),
    );
  };

  const catchFailure = (error: unknown) => {
    const revealed = revealInvalidGraph(error);
    if (revealed) return revealed.catch(notifyError);
    notifyError(error);
  };

  if (loading) {
    return <PageChrome title={t("channels.title")} status="loading" />;
  }
  if (loadError || !channel || !graph) {
    return (
      <PageChrome
        title={t("channels.title")}
        status={loadError ? "error" : "notFound"}
        errorMessage={
          loadError ? problemMessage(t, loadError, t("channels.load.failed")) : undefined
        }
        requestId={loadError?.requestId}
        onRetry={loadError ? () => setReloadToken((value) => value + 1) : undefined}
      />
    );
  }
  if (mode === "edit" && canWrite?.can === false) {
    return <PageChrome title={t("channels.title")} status="loading" />;
  }

  const persist = async (draftGraph?: Graph): Promise<{ revision: number; graph: Graph }> => {
    let nextRevision = revision;
    let nextGraph = draftGraph ?? graph;
    const nameError = nameEditorRef.current?.commit() ?? null;
    if (nameError) {
      throw new RecordInvalid(nameError);
    }
    const pendingName = form.getValues().name.trim();
    if (!pendingName || pendingName.length > NAME_MAX) {
      const message = pendingName
        ? t("channels.validation.name.length")
        : t("channels.validation.name.required");
      nameEditorRef.current?.showError(message);
      throw new RecordInvalid(message);
    }
    if (form.isDirty()) {
      const values = form.getValues();
      const description = values.description.trim();
      const descriptionValue = description ? description : null;
      let saved = channel;
      if (
        values.name.trim() !== saved.name ||
        descriptionValue !== (saved.description ?? null)
      ) {
        const updated = await patchChannel(channelId, {
          name: values.name.trim(),
          description: descriptionValue,
        });
        saved = updated.channel;
        setChannel(saved);
      }
      if (values.active !== saved.active) {
        const updated = values.active
          ? await activateChannel(channelId)
          : await deactivateChannel(channelId);
        saved = updated.channel;
        setChannel(saved);
      }
      form.markSaved();
    }
    if (JSON.stringify(nextGraph) !== baseline) {
      const saved = await saveDraft(channelId, {
        base_revision: nextRevision,
        graph: nextGraph,
      });
      nextRevision = saved.draft_revision;
      nextGraph = graphWithoutUnsetIntegers(saved.graph, catalog);
      setRevision(saved.draft_revision);
      setGraph(nextGraph);
      setBaseline(JSON.stringify(nextGraph));
      setAdoptToken((token) => token + 1);
    }
    return { revision: nextRevision, graph: nextGraph };
  };

  const rememberRun = async (jobId: string) => {
    const epoch = ++runEpoch.current;
    const detail = await getRun(channelId, jobId);
    if (runEpoch.current !== epoch) return;
    setSessionRun(detail);
  };

  const openRun = (stopAt: string | null) => {
    setRunRequest({ stopAt });
  };

  const templatePreview: ChannelTemplatePreview | null = canWrite?.can
    ? {
        run: sessionRun
          ? {
              key: recordedKey(sessionRun),
              evaluate: (nodeId, path) =>
                previewTemplate(channelId, sessionRun.run.job_id, {
                  graph,
                  node_id: nodeId,
                  path,
                }),
            }
          : null,
      }
    : null;

  const occupyPage = (): boolean => {
    if (pageMutation.current) return false;
    pageMutation.current = true;
    setBusy(true);
    return true;
  };

  const releasePage = () => {
    pageMutation.current = false;
    setBusy(false);
  };

  const launch = () => {
    const stopAt = runRequest?.stopAt ?? null;
    if (!graph || runActive) return;
    const triggers = graph.nodes.filter((node) => node.type.startsWith("trigger."));
    if (triggers.length !== 1) {
      notifyError(new Error(t("channels.run.needTrigger")));
      return;
    }
    if (!occupyPage()) return;
    void (async () => {
      await persist();
      const started = await startRun(channelId, {
        target: "draft",
        ignore_checkpoints: false,
        stop_at_node_id: stopAt,
      });
      await rememberRun(started.run.job_id);
      setRunRequest(null);
    })()
      .catch(catchFailure)
      .finally(releasePage);
  };

  const stopRun = () => {
    if (!sessionRun || !channel) return;
    const jobId = sessionRun.run.job_id;
    const recordName = form.values.name || channel.name;
    stopRunAction.run({
      safety: "confirm",
      recordName,
      title: t("channels.run.stop.confirmTitle", { name: recordName }),
      consequence: t("channels.run.stop.consequence"),
      confirmLabel: t("channels.run.stop"),
      confirmColor: "red",
      outcome: t("channels.run.stop.outcome"),
      execute: async () => {
        setBusy(true);
        try {
          await cancelJob(jobId);
          setSessionRun(await getRun(channelId, jobId));
        } finally {
          setBusy(false);
        }
      },
    });
  };

  const runStopAt = runRequest?.stopAt ?? null;
  const runNode = runStopAt ? graph.nodes.find((node) => node.id === runStopAt) : undefined;
  const runNodeName = runNode ? runNode.name || runNode.ref : null;

  const showEdit = mode === "show" && Boolean(canWrite?.can);
  const showLifecycle = Boolean(canWrite?.can);
  const startPublish = () => {
    if (!occupyPage()) return;
    void persist()
      .then(async ({ revision: nextRevision, graph: savedGraph }) => {
        const result = await validateDraft(channelId, savedGraph);
        if (!result.valid) {
          reportBlockedGraph(result, savedGraph);
          return;
        }
        if (!validationResultApplies(savedGraph, graphRef.current)) return;
        validateSeq.current += 1;
        setProblems(result.problems);
        setPorts(result.ports);
        setExpressionContext(result.context);
        setPublishRevision(nextRevision);
        setPreview(await previewPublish(channelId));
      })
      .catch(notifyError)
      .finally(releasePage);
  };

  const descriptionText = form.values.description.trim();
  const versionLabel = channel.latest_version
    ? `v${channel.latest_version.number}`
    : t("channels.versions.unpublished");
  const togglePanel = (next: "versions" | "runs") => {
    setPanel((current) => (current === next ? null : next));
  };
  const loadErrorChannels = () => {
    setErrorChannelsFailed(false);
    void listChannels({ limit: 200 })
      .then(async (page) => {
        const found = await Promise.all(
          page.items
            .filter((item) => item.id !== channelId && item.latest_version)
            .map(async (item) => {
              const loaded = await getVersion(item.id, item.latest_version!.number);
              const triggers = (loaded.version.graph?.nodes ?? []).filter((node) =>
                node.type.startsWith("trigger."),
              );
              if (triggers.length === 1 && triggers[0]?.type === "trigger.error") {
                return { value: item.id, label: item.name };
              }
              return null;
            }),
        );
        setErrorChannels(
          found.filter((item): item is { value: string; label: string } => item != null),
        );
        setErrorChannelsFailed(false);
      })
      .catch(() => {
        setErrorChannels([]);
        setErrorChannelsFailed(true);
      });
  };
  const openDescription = () => {
    detailsForm.setValues({
      description: form.values.description,
      timeout: graph.settings.run_timeout_sec ?? "",
      retryLimit: graph.settings.run_retry_limit ?? "",
      errorChannelId: graph.settings.error_channel_id,
    });
    detailsForm.markSaved();
    setDescriptionOpen(true);
    loadErrorChannels();
  };
  const closeDescription = () => {
    detailsForm.reset();
    setDescriptionOpen(false);
  };
  const applyDescription = (values: {
    description: string;
    timeout: number | string;
    retryLimit: number | string;
    errorChannelId: string | null;
  }) => {
    form.setFieldValue("description", values.description.trim().slice(0, DESCRIPTION_MAX));
    const next = runTimeoutSec(values.timeout);
    const retryLimit = runRetryLimit(values.retryLimit);
    setGraph((current) =>
      current
        ? {
            ...current,
            settings: {
              ...current.settings,
              run_timeout_sec: next,
              run_retry_limit: retryLimit,
              error_channel_id: values.errorChannelId,
            },
          }
        : current,
    );
    detailsForm.markSaved();
    setDescriptionOpen(false);
  };

  return (
    // Above app chrome (100/101) and below modal (200) and popover (300).
    <Box
      flex={1}
      h="100%"
      mih={0}
      style={{
        position: "relative",
        zIndex: 150,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
    <PageChrome
      fill
      title={t("channels.title")}
      recordTitle={form.values.name || channel.name}
      recent={{
        moduleId: "channels",
        title: form.values.name || channel.name,
      }}
      titleSlot={
        <ChannelNameHeading
          ref={nameEditorRef}
          key={`${channel.id}:${channel.updated_at.toJSON()}`}
          name={form.values.name}
          editable={draftEditable && !busy}
          onCommit={(name) => form.setFieldValue("name", name)}
        />
      }
      titleExtra={
        <>
          <ChannelActiveStatus
            active={form.values.active}
            editable={draftEditable && !busy}
            onToggle={() => form.setFieldValue("active", !form.values.active)}
          />
          {channel.persistently_failing ? (
            <StatusBadge tone="warning" labelKey="channels.persistentlyFailing" />
          ) : null}
          <Group gap={4} wrap="nowrap">
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              aria-expanded={panel === "versions"}
              aria-label={t("channels.versions.open", { version: versionLabel })}
              leftSection={<VersionsIcon size={14} />}
              onClick={() => togglePanel("versions")}
            >
              {versionLabel}
            </Button>
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              aria-expanded={panel === "runs"}
              leftSection={<ListIcon size={14} />}
              onClick={() => togglePanel("runs")}
            >
              {t("channels.tabs.runs")}
            </Button>
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              leftSection={<AdjustmentsIcon size={14} />}
              onClick={openDescription}
            >
              {t("channels.details.title")}
            </Button>
          </Group>
        </>
      }
      actions={
        <HeaderActions
          navigation={
            <Button
              component={ConsoleLink}
              href="/console/channels"
              variant="default"
              size="sm"
            >
              {t("channels.actions.back")}
            </Button>
          }
          lifecycle={
            writable || (runActive && canStop) || showLifecycle ? (
              <>
                {writable ? (
                  <Button
                    size="sm"
                    variant="light"
                    loading={busy}
                    disabled={!draftEditable}
                    onClick={() => openRun(null)}
                  >
                    {t("channels.run.open")}
                  </Button>
                ) : null}
                {runActive && canStop ? (
                  <Button
                    size="sm"
                    color="red"
                    variant="light"
                    loading={busy || stopRunAction.submitting}
                    onClick={stopRun}
                  >
                    {t("channels.run.stop")}
                  </Button>
                ) : null}
                {showLifecycle ? (
                  mode === "show" ? (
                    <HeaderAction primary>
                      <Button
                        size="sm"
                        loading={busy}
                        disabled={draftAccess === "locked"}
                        onClick={startPublish}
                      >
                        {t("channels.actions.publish")}
                      </Button>
                    </HeaderAction>
                  ) : (
                    <Button
                      size="sm"
                      variant="light"
                      loading={busy}
                      disabled={draftAccess === "locked"}
                      onClick={startPublish}
                    >
                      {t("channels.actions.publish")}
                    </Button>
                  )
                ) : null}
              </>
            ) : null
          }
          standard={
            showEdit || canWrite?.can || writable ? (
              <>
                {showEdit ? (
                  <Button
                    component={ConsoleLink}
                    href={`/console/channels/${channelId}/edit`}
                    size="sm"
                    variant="light"
                  >
                    {t("actions.edit")}
                  </Button>
                ) : null}
                {canWrite?.can ? (
                  <Button
                    size="sm"
                    color="red"
                    variant="light"
                    loading={deleteAction.isSubmitting("delete")}
                    onClick={() => {
                      deleteAction.run({
                        safety: "confirm",
                        key: "delete",
                        recordName: channel?.name || channelId,
                        title: t("channels.delete.title"),
                        consequence: t("channels.delete.consequence"),
                        confirmLabel: t("actions.delete"),
                        confirmColor: "red",
                        outcome: t("channels.delete.outcome"),
                        execute: async () => {
                          await deleteChannel(channelId);
                          suppressLeaveGuard();
                          window.location.replace("/console/channels");
                        },
                      });
                    }}
                  >
                    {t("actions.delete")}
                  </Button>
                ) : null}
                {writable ? (
                  <Button
                    component={ConsoleLink}
                    href={`/console/channels/${channelId}`}
                    variant="default"
                    size="sm"
                  >
                    {t("common.cancel")}
                  </Button>
                ) : null}
                {writable ? (
                  <HeaderAction primary>
                    <Button
                      type="submit"
                      form={FORM_ID}
                      size="sm"
                      loading={form.submitting}
                      disabled={!draftEditable}
                    >
                      {t("channels.edit.submit")}
                    </Button>
                  </HeaderAction>
                ) : null}
              </>
            ) : null
          }
        />
      }
    >
      <form
        id={FORM_ID}
        hidden
        onSubmit={form.onSubmit(
          async () => {
            if (!occupyPage()) throw new PageMutationOccupied();
            try {
              await persist();
              form.markSaved();
              setSaveFailure(null);
              open?.({ type: "success", message: t("channels.edit.success") });
            } catch (error) {
              if (error instanceof RecordInvalid || error instanceof PageMutationOccupied) throw error;
              setSaveFailure(
                saveFailureFrom(
                  t,
                  error,
                  form.applyApiError(error),
                  t("channels.save.failed"),
                ),
              );
            } finally {
              releasePage();
            }
          },
          (errors) => {
            const nameError = errors.name;
            if (typeof nameError === "string") {
              nameEditorRef.current?.showError(nameError);
            }
          },
        )}
      />
      <FillColumn>
        <FormErrorSummary failure={saveFailure} />
        <LiveStatusAnnouncer
          text={
            runLive.data
              ? t(presentJobStatus(runLive.data.run.status).labelKey)
              : ""
          }
        />
        {runLive.stale ? (
          <StaleNotice
            hasData={sessionRun != null || runLive.data != null}
            onRetry={() => void runLive.refresh()}
          />
        ) : null}
        <ChannelCanvas
          key={draftEpoch}
          channelId={channelId}
          graph={graph}
          catalog={catalog}
          appearance={writable ? "edit" : "browse"}
          mutable={draftEditable}
          adoptToken={adoptToken}
          problems={problems}
          ports={ports}
          context={expressionContext}
          onChange={setGraph}
          sessionRun={sessionRun}
          templatePreview={templatePreview}
          onRun={openRun}
        />
      </FillColumn>
      <Modal
        opened={runRequest != null}
        onClose={() => setRunRequest(null)}
        title={runNodeName != null ? t("channels.run.upTo", { node: runNodeName }) : t("channels.run.open")}
      >
        <Stack gap="sm">
          <Text size="sm">
            {runNodeName != null
              ? t("channels.run.writesUpTo", { node: runNodeName })
              : t("channels.run.writes")}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" disabled={busy} onClick={() => setRunRequest(null)}>
              {t("common.cancel")}
            </Button>
            <Button loading={busy} onClick={() => launch()}>
              {t("channels.run.confirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      {draftEditable ? (
        <FormDialog
          opened={descriptionOpen}
          onClose={closeDescription}
          title={t("channels.details.title")}
          dirty={detailsForm.dirty}
          submitting={detailsForm.submitting}
          submitLabel={t("channels.description.apply")}
          onSubmit={() => void detailsForm.submit(applyDescription)}
        >
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              {t("channels.description.hint")}
            </Text>
            <Textarea
              label={t("channels.fields.description")}
              placeholder={t("channels.description.optional")}
              autosize
              minRows={3}
              maxRows={12}
              {...detailsForm.fieldProps("description")}
              onChange={(event) =>
                detailsForm.setFieldValue(
                  "description",
                  event.currentTarget.value.slice(0, DESCRIPTION_MAX),
                )
              }
            />
            <NumberField
              editable
              label={t("channels.settings.runTimeout")}
              description={t("channels.settings.runTimeoutHint")}
              min={1}
              w={280}
              {...detailsForm.fieldProps("timeout")}
            />
            <NumberField
              editable
              label={t("channels.settings.runRetryLimit")}
              description={t("channels.settings.runRetryLimitHint")}
              min={0}
              max={10}
              allowDecimal={false}
              w={280}
              {...detailsForm.fieldProps("retryLimit")}
            />
            <SelectField
              editable
              label={t("channels.settings.errorChannel")}
              description={t("channels.settings.errorChannelHint")}
              data={errorChannelOptions(
                errorChannels,
                detailsForm.values.errorChannelId,
              )}
              value={detailsForm.values.errorChannelId}
              error={
                errorChannelsFailed ? t("channels.settings.errorChannelLoadFailed") : undefined
              }
              clearable
              onChange={(next) => detailsForm.setFieldValue("errorChannelId", next)}
            />
          </Stack>
        </FormDialog>
      ) : (
        <Modal
          opened={descriptionOpen}
          onClose={closeDescription}
          title={t("channels.details.title")}
        >
          <Stack gap="sm">
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                {t("channels.fields.description")}
              </Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                {descriptionText || t("channels.description.empty")}
              </Text>
            </Stack>
            <NumberField
              editable={false}
              label={t("channels.settings.runTimeout")}
              description={t("channels.settings.runTimeoutHint")}
              w={280}
              value={graph.settings.run_timeout_sec ?? ""}
            />
            <NumberField
              editable={false}
              label={t("channels.settings.runRetryLimit")}
              description={t("channels.settings.runRetryLimitHint")}
              w={280}
              value={graph.settings.run_retry_limit ?? ""}
            />
            <SelectField
              editable={false}
              label={t("channels.settings.errorChannel")}
              description={t("channels.settings.errorChannelHint")}
              data={errorChannelOptions(errorChannels, graph.settings.error_channel_id)}
              value={graph.settings.error_channel_id}
              error={
                errorChannelsFailed ? t("channels.settings.errorChannelLoadFailed") : undefined
              }
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={closeDescription}>
                {t("channels.description.close")}
              </Button>
            </Group>
          </Stack>
        </Modal>
      )}
      {stopRunAction.dialog}
      <ConfirmActionModal
        opened={preview != null}
        onClose={() => setPreview(null)}
        title={t("channels.publish.title")}
        confirmLabel={t("channels.publish.confirm")}
        loading={busy}
        onConfirm={() => {
          if (!occupyPage()) return;
          void publishChannel(channelId, publishRevision)
            .then(async () => {
              setPreview(null);
              setProblems([]);
              setPorts([]);
              setExpressionContext(null);
              open?.({ type: "success", message: t("channels.publish.done") });
              setReloadToken((value) => value + 1);
            })
            .catch(catchFailure)
            .finally(releasePage);
        }}
      >
        <Stack gap="xs">
          <Text size="sm">{t("channels.publish.mirrors")}</Text>
          <Text size="sm" c="dimmed">
            {preview && preview.mirrors_to_open.length > 0
              ? preview.mirrors_to_open.map((item) => item.locator).join(", ")
              : t("channels.publish.mirrorsEmpty")}
          </Text>
          <Text size="sm">{t("channels.publish.runs")}</Text>
          {preview && preview.runs_to_cancel.length > 0 ? (
            <Stack gap={4}>
              {preview.runs_to_cancel.map((item) => (
                <JobReference
                  key={item.job_id}
                  jobId={item.job_id}
                  kind="channel_run"
                  onOpen={setPublishJobId}
                />
              ))}
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              {t("channels.publish.runsEmpty")}
            </Text>
          )}
          {preview?.missing_run_timeout ? (
            <Text size="sm" c="orange">
              {t("channels.publish.missingTimeout")}
            </Text>
          ) : null}
        </Stack>
      </ConfirmActionModal>
      {publishJobId ? (
        <JobDetailModal
          jobId={publishJobId}
          opened
          onClose={() => setPublishJobId(null)}
        />
      ) : null}
      {deleteAction.dialog}
    </PageChrome>
    <Box
      className="channel-record-overlays"
      pos="absolute"
      inset={0}
      style={{ zIndex: 20, pointerEvents: "none" }}
    >
      <Drawer
        opened={panel === "versions"}
        onClose={() => setPanel(null)}
        position="right"
        size="xl"
        withinPortal={false}
        withOverlay={false}
        lockScroll={false}
        trapFocus={false}
        zIndex={20}
        title={t("channels.tabs.versions")}
      >
        {panel === "versions" ? (
          <ChannelVersions channelId={channelId} reloadToken={reloadToken} />
        ) : null}
      </Drawer>
      <Drawer
        opened={panel === "runs"}
        onClose={() => setPanel(null)}
        position="right"
        size="xl"
        withinPortal={false}
        withOverlay={false}
        lockScroll={false}
        trapFocus={false}
        zIndex={20}
        title={t("channels.tabs.runs")}
      >
        {panel === "runs" ? <ChannelRuns channelId={channelId} /> : null}
      </Drawer>
    </Box>
    </Box>
  );
}

type ChannelNameHeadingHandle = {
  commit: () => string | null;
  showError: (message: string) => void;
};

const ChannelNameHeading = forwardRef<
  ChannelNameHeadingHandle,
  {
    name: string;
    editable: boolean;
    onCommit: (name: string) => void;
  }
>(function ChannelNameHeading({ name, editable, onCommit }, ref) {
  const t = useTranslate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const editingRef = useRef(false);
  const draftRef = useRef(name);
  editingRef.current = editing;
  draftRef.current = draft;

  useEffect(() => {
    if (!editing) setDraft(name);
  }, [editing, name]);

  useEffect(() => {
    if (!editing) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  const finish = (raw: string): string | null => {
    if (!editingRef.current) return null;
    const next = raw.trim();
    if (!next) {
      const message = t("channels.validation.name.required");
      setError(message);
      setEditing(true);
      return message;
    }
    if (next.length > NAME_MAX) {
      const message = t("channels.validation.name.length");
      setError(message);
      setEditing(true);
      return message;
    }
    editingRef.current = false;
    onCommit(next);
    setDraft(next);
    setError(null);
    setEditing(false);
    return null;
  };

  useImperativeHandle(ref, () => ({
    commit: () => finish(draftRef.current),
    showError: (message: string) => {
      editingRef.current = true;
      setError(message);
      setEditing(true);
    },
  }));

  if (!editable) {
    return <Title order={2}>{name}</Title>;
  }

  if (!editing) {
    return (
      <Title order={2}>
        <Tooltip label={t("channels.name.edit")}>
          <UnstyledButton
            onClick={() => {
              setDraft(name);
              setError(null);
              editingRef.current = true;
              setEditing(true);
            }}
            style={{
              font: "inherit",
              color: "inherit",
              textAlign: "left",
              cursor: "pointer",
              textDecoration: "underline",
              textDecorationStyle: "dotted",
              textUnderlineOffset: "0.15em",
            }}
          >
            {name}
          </UnstyledButton>
        </Tooltip>
      </Title>
    );
  }

  return (
    <TextInput
      ref={inputRef}
      aria-label={t("channels.fields.name")}
      value={draft}
      error={error}
      description={error ? t("channels.name.revert") : undefined}
      maxLength={NAME_MAX}
      w={360}
      onChange={(event) => {
        const value = event.currentTarget.value;
        draftRef.current = value;
        setDraft(value);
        if (error && value.trim()) setError(null);
      }}
      onBlur={() => {
        finish(draftRef.current);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(draftRef.current);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          editingRef.current = false;
          setDraft(name);
          setError(null);
          setEditing(false);
        }
      }}
      styles={{
        input: {
          fontWeight: 700,
          fontSize: "var(--mantine-h2-font-size)",
        },
      }}
    />
  );
});

function ChannelActiveStatus({
  active,
  editable,
  onToggle,
}: {
  active: boolean;
  editable: boolean;
  onToggle: () => void;
}) {
  const t = useTranslate();
  if (!editable) {
    const presentation = presentChannelActive(active);
    return (
      <StatusBadge
        size="sm"
        tone={presentation.tone}
        labelKey={presentation.labelKey}
      />
    );
  }
  return (
    <Switch
      size="sm"
      label={t("channels.fields.active")}
      checked={active}
      disabled={!editable}
      onChange={onToggle}
      styles={{ body: { alignItems: "center" } }}
    />
  );
}

function IdentityFields({
  form,
  editable,
}: {
  form: {
    fieldProps: (path: "name" | "description") => object;
  };
  editable: boolean;
}) {
  const t = useTranslate();
  return (
    <Stack>
      <TextField
        editable={editable}
        label={t("channels.fields.name")}
        required={editable}
        {...form.fieldProps("name")}
      />
      <TextareaField
        editable={editable}
        label={t("channels.fields.description")}
        {...form.fieldProps("description")}
      />
    </Stack>
  );
}
