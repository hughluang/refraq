"use client";

import { Suspense } from "react";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { SourceDiagnostics } from "@/features/mirrors/SourceDiagnostics";

export default function DiagnosticsPage() {
  return <Suspense fallback={<PageBodySkeleton />}><SourceDiagnostics /></Suspense>;
}
