"use client";

import {
  PasswordInput as MantinePasswordInput,
  type PasswordInputProps,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";

/** Password field whose visibility control is named from the locale catalog. */
export function PasswordInput({
  visibilityToggleButtonProps,
  ...props
}: PasswordInputProps) {
  const t = useTranslate();
  return (
    <MantinePasswordInput
      {...props}
      visibilityToggleButtonProps={{
        ...visibilityToggleButtonProps,
        "aria-label": t("auth.password.visibility"),
      }}
    />
  );
}
