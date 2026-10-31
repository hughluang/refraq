"use client";

import type { NotificationProvider } from "@refinedev/core";
import { Notifications, notifications } from "@mantine/notifications";
import { createElement, type ReactNode } from "react";

import { AlertIcon, CheckIcon, ErrorIcon, InfoIcon } from "@/components/icons";
import { translateKey } from "@/providers/i18n-runtime";

export type ConsoleNoticeType = "success" | "info" | "warning" | "error";

type PresentInput = {
  id?: string;
  title?: ReactNode;
  message?: ReactNode;
  type: ConsoleNoticeType;
  /** Overrides the type default. Success and info close after 4s; warning and error stay open. */
  autoClose?: number | false;
};

const VISIBLE_LIMIT = 3;

type VisibleNotice = {
  id: string;
  type: ConsoleNoticeType;
  originalTitle: ReactNode;
  count: number;
};

const visible: VisibleNotice[] = [];
let sequence = 0;

function forget(id: string) {
  const index = visible.findIndex((notice) => notice.id === id);
  if (index >= 0) visible.splice(index, 1);
}

function isTransient(type: ConsoleNoticeType): boolean {
  return type === "success" || type === "info";
}

function makeRoom() {
  if (visible.length < VISIBLE_LIMIT) return;
  const transient = visible.findIndex((notice) => isTransient(notice.type));
  const index = transient >= 0 ? transient : 0;
  const [victim] = visible.splice(index, 1);
  notifications.hide(victim.id);
}

function iconFor(type: ConsoleNoticeType) {
  if (type === "success") return createElement(CheckIcon);
  if (type === "info") return createElement(InfoIcon);
  if (type === "warning") return createElement(AlertIcon);
  return createElement(ErrorIcon);
}

function colorFor(type: ConsoleNoticeType) {
  if (type === "success") return "green";
  if (type === "info") return "blue";
  if (type === "warning") return "yellow";
  return "red";
}

function autoCloseFor(type: ConsoleNoticeType, override: number | false | undefined) {
  if (override !== undefined) return override;
  return isTransient(type) ? 4000 : false;
}

function repeatedPhrase(count: number): string {
  return translateKey("feedback.repeated").split("{{count}}").join(String(count));
}

function displayTitle(notice: VisibleNotice): ReactNode {
  if (notice.count < 2) return notice.originalTitle;
  return `${notice.originalTitle} ${repeatedPhrase(notice.count)}`;
}

function sameOutcome(notice: VisibleNotice, input: PresentInput): boolean {
  return (
    notice.type === input.type &&
    typeof notice.originalTitle === "string" &&
    notice.originalTitle === input.title
  );
}

function payloadFor(notice: VisibleNotice, input: PresentInput) {
  return {
    id: notice.id,
    title: displayTitle(notice),
    message: input.message ?? "",
    color: colorFor(notice.type),
    icon: iconFor(notice.type),
    autoClose: autoCloseFor(notice.type, input.autoClose),
    onClose: () => {
      forget(notice.id);
    },
  };
}

/**
 * Show a console notification, or update one that is already open.
 * A repeat of the same type and original title updates the visible notice.
 */
export function presentConsoleNotification(input: PresentInput): string {
  const byId = input.id ? visible.find((notice) => notice.id === input.id) : undefined;
  if (byId) {
    byId.type = input.type;
    byId.originalTitle = input.title;
    byId.count = 1;
    notifications.update(payloadFor(byId, input));
    return byId.id;
  }

  const repeat = visible.find((notice) => sameOutcome(notice, input));
  if (repeat) {
    repeat.count += 1;
    notifications.update(payloadFor(repeat, input));
    return repeat.id;
  }

  const id = input.id ?? `console-notice-${sequence++}`;
  const created: VisibleNotice = {
    id,
    type: input.type,
    originalTitle: input.title,
    count: 1,
  };
  makeRoom();
  notifications.show(payloadFor(created, input));
  visible.push(created);
  return id;
}

export function dismissConsoleNotification(id: string) {
  notifications.hide(id);
  forget(id);
}

export function ConsoleNotifications() {
  return createElement(Notifications, { position: "top-right", limit: VISIBLE_LIMIT });
}

function noticeType(type: string | undefined): ConsoleNoticeType {
  if (type === "error") return "error";
  if (type === "warning") return "warning";
  if (type === "info" || type === "progress") return "info";
  return "success";
}

export const notificationProvider: NotificationProvider = {
  open: ({ key, message, description, type }) => {
    presentConsoleNotification({
      id: key,
      title: message,
      message: description,
      type: noticeType(type),
    });
  },
  close: (key) => {
    dismissConsoleNotification(key);
  },
};
