"use client";

import { Button, Group, Modal } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { usePathname } from "next/navigation";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { isLeaveHref } from "@/hooks/leaveGuard";

type Listener = () => void;
type Waiter = (allowed: boolean) => void;

const entries = new Map<string, boolean>();
const dirtyListeners = new Set<Listener>();
const promptListeners = new Set<Listener>();
let dirtySnapshot = false;
let suppressed = false;
let promptOpen = false;
let promptVersion = 0;
let waiters: Waiter[] = [];

function emitDirty() {
  for (const listener of dirtyListeners) listener();
}

function emitPrompt() {
  promptVersion += 1;
  for (const listener of promptListeners) listener();
}

function recomputeDirty() {
  let next = false;
  for (const dirty of entries.values()) {
    if (dirty) {
      next = true;
      break;
    }
  }
  if (next === dirtySnapshot) return;
  dirtySnapshot = next;
  emitDirty();
}

export function isLeaveBlocked(): boolean {
  if (suppressed) return false;
  for (const dirty of entries.values()) {
    if (dirty) return true;
  }
  return false;
}

export function navigationNeedsConfirm(nextHref: string): boolean {
  if (!isLeaveHref(window.location.href, nextHref)) return false;
  return isLeaveBlocked();
}

export function hasDirtyRegistration() {
  return dirtySnapshot;
}

export function subscribeDirty(listener: Listener) {
  dirtyListeners.add(listener);
  return () => {
    dirtyListeners.delete(listener);
  };
}

export function leavePromptOpen() {
  return promptOpen;
}

export function leavePromptSnapshot() {
  return promptVersion;
}

export function subscribeLeavePrompt(listener: Listener) {
  promptListeners.add(listener);
  return () => {
    promptListeners.delete(listener);
  };
}

/** Lets the next leave through. Used after a save or delete that navigates while dirty state has not re-rendered. */
export function suppressLeaveGuard(): void {
  suppressed = true;
}

export function releaseLeaveGuardSuppression(): void {
  suppressed = false;
}

export function confirmLeave(): Promise<boolean> {
  if (!isLeaveBlocked()) return Promise.resolve(true);
  return new Promise((resolve) => {
    waiters.push(resolve);
    if (!promptOpen) {
      promptOpen = true;
      emitPrompt();
    }
  });
}

export function settleLeavePrompt(allowed: boolean) {
  if (!promptOpen && waiters.length === 0) return;
  if (allowed) suppressed = true;
  promptOpen = false;
  const current = waiters;
  waiters = [];
  emitPrompt();
  for (const resolve of current) resolve(allowed);
}

export function useLeaveGuardRegistration(dirty: boolean): void {
  const id = useId();
  useLayoutEffect(() => {
    entries.set(id, dirty);
    recomputeDirty();
    return () => {
      entries.delete(id);
      recomputeDirty();
    };
  }, [id, dirty]);
}

function LeaveGuardDialog({ opened }: { opened: boolean }) {
  const t = useTranslate();
  return (
    <Modal
      opened={opened}
      onClose={() => settleLeavePrompt(false)}
      title={t("layout.leave.title")}
      centered
    >
      <Group justify="flex-end">
        <Button
          data-autofocus
          variant="default"
          onClick={() => settleLeavePrompt(false)}
        >
          {t("layout.leave.stay")}
        </Button>
        <Button color="red" onClick={() => settleLeavePrompt(true)}>
          {t("layout.leave.discard")}
        </Button>
      </Group>
    </Modal>
  );
}

export function LeaveGuardProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const dirty = useSyncExternalStore(
    subscribeDirty,
    hasDirtyRegistration,
    () => false,
  );
  useSyncExternalStore(subscribeLeavePrompt, leavePromptSnapshot, () => 0);
  const opened = leavePromptOpen();

  useEffect(() => {
    releaseLeaveGuardSuppression();
  }, [pathname]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!isLeaveBlocked()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  return (
    <>
      {children}
      <LeaveGuardDialog opened={opened} />
    </>
  );
}
