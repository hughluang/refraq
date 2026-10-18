"use client";

import type { NotificationProvider } from "@refinedev/core";
import { Notifications, notifications } from "@mantine/notifications";
import { createElement, type ReactNode } from "react";

import { CheckIcon, ErrorIcon } from "@/components/icons";

export type ConsoleNoticeType = "success" | "error";

type PresentInput = {
  id?: string;
  title?: ReactNode;
  message?: ReactNode;
  type: ConsoleNoticeType;
  /** Overrides the type default. Success closes after 4s; errors stay open. */
  autoClose?: number | false;
};

const shown = new Set<string>();
let sequence = 0;

function iconFor(type: ConsoleNoticeType) {
  if (type === "success") return createElement(CheckIcon);
  return createElement(ErrorIcon);
}

function colorFor(type: ConsoleNoticeType) {
  if (type === "success") return "green";
  return "red";
}

function autoCloseFor(type: ConsoleNoticeType, override: number | false | undefined) {
  if (override !== undefined) return override;
  if (type === "success") return 4000;
  return false;
}

/**
 * Show a console notification, or update one that is already open.
 */
export function presentConsoleNotification(input: PresentInput): string {
  const id = input.id ?? `console-notice-${sequence++}`;
  const payload = {
    id,
    title: input.title,
    message: input.message ?? "",
    color: colorFor(input.type),
    icon: iconFor(input.type),
    autoClose: autoCloseFor(input.type, input.autoClose),
    onClose: () => {
      shown.delete(id);
    },
  };
  if (shown.has(id)) {
    notifications.update(payload);
  } else {
    notifications.show(payload);
    shown.add(id);
  }
  return id;
}

export function dismissConsoleNotification(id: string) {
  notifications.hide(id);
  shown.delete(id);
}

export function ConsoleNotifications() {
  return createElement(Notifications, { position: "top-right", limit: 3 });
}

function noticeType(type: string | undefined): ConsoleNoticeType {
  return type === "error" ? "error" : "success";
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
