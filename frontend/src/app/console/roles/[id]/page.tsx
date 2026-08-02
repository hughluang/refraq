"use client";

import { useParams } from "next/navigation";

import { RoleForm } from "@/features/roles/RoleForm";

export default function RoleEditPage() {
  const params = useParams<{ id: string }>();
  return <RoleForm mode="edit" roleId={params.id} />;
}
