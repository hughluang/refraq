import type { ReactNode } from "react";

import { LangSwitcher } from "@/components/LangSwitcher";

export default function DashboardLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <main>
      <header>
        <h1>refraq Dashboard</h1>
        <LangSwitcher />
      </header>
      <section>{children}</section>
    </main>
  );
}
