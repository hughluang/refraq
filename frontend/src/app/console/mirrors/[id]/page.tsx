"use client";

import { useParams, useSearchParams } from "next/navigation";
import { MirrorDetail } from "@/features/mirrors/MirrorDetail";

export default function MirrorPage() {
  const { id } = useParams<{ id: string }>();
  const query = useSearchParams();
  const channelId = query.get("channel");
  const version = Number(query.get("version"));
  return <MirrorDetail key={id} id={id} channelId={channelId} version={version} />;
}
