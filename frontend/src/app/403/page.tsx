"use client";

import { Center, Paper } from "@mantine/core";

import { ForbiddenState } from "@/components/feedback/ForbiddenState";

export default function ForbiddenPage() {
  return (
    <Center mih="100vh" p="md">
      <Paper p="xl" withBorder w={420}>
        <ForbiddenState />
      </Paper>
    </Center>
  );
}
