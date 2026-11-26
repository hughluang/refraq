"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { ChannelRunDetail } from "@/features/channels/ChannelRunDetail";

export default function ChannelRunPage() {
  const params = useParams<{ id: string; jobId: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <ChannelRunDetail channelId={params.id} jobId={params.jobId} />
    </Suspense>
  );
}
