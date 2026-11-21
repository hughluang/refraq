"use client";

import { useParams } from "next/navigation";
import { MirrorDetail } from "@/features/mirrors/MirrorDetail";

export default function MirrorPage() {
  const { id } = useParams<{ id: string }>();
  return <MirrorDetail key={id} id={id} />;
}
