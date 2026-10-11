"use client";

import { useParams } from "next/navigation";

import { ChannelRunDetail } from "@/features/channels/ChannelRunDetail";

export default function ChannelRunPage() {
  const params = useParams<{ id: string; jobId: string }>();
  return <ChannelRunDetail channelId={params.id} jobId={params.jobId} />;
}
