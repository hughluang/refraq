"use client";

import type { NotificationProvider } from "@refinedev/core";
import { notifications } from "@mantine/notifications";

export const notificationProvider: NotificationProvider = {
  open: ({ key, message, description, type }) => {
    const color =
      type === "success" ? "green" : type === "error" ? "red" : "blue";
    notifications.show({
      id: key,
      title: message,
      message: description,
      color,
      loading: type === "progress",
      autoClose: type === "progress" ? false : 4000,
    });
  },
  close: (key) => {
    notifications.hide(key);
  },
};
