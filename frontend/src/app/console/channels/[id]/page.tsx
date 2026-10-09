"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { ChannelRecord } from "@/features/channels/ChannelRecord";

export default function ChannelDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <ChannelRecord mode="show" channelId={params.id} />
    </Suspense>
  );
}
