"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { ChannelRecord } from "@/features/channels/ChannelRecord";

export default function ChannelCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <ChannelRecord mode="create" />
    </Suspense>
  );
}
