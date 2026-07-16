import type { ReactNode } from "react";
import { ConceptAssistant } from "../ConceptAssistant";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const activePath = window.location.pathname;

  return (
    <div className="flex min-h-screen">
      <Sidebar activePath={activePath} />
      <div className="flex min-h-screen flex-1 flex-col overflow-x-hidden">
        <Topbar activePath={activePath} />
        <div className="flex-1">{children}</div>
      </div>
      <ConceptAssistant />
    </div>
  );
}
