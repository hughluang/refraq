"use client";

import { Suspense } from "react";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { MirrorSetup } from "@/features/mirrors/setup/MirrorSetup";

export default function MirrorSetupPage() {
  return <Suspense fallback={<PageBodySkeleton />}><MirrorSetup /></Suspense>;
}
