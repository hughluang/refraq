"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { ChannelRecord } from "@/features/channels/ChannelRecord";

export default function ChannelEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <ChannelRecord mode="edit" channelId={params.id} />
    </Suspense>
  );
}
