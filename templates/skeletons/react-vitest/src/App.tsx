import { AppShell, type NavLink } from "./ui/AppShell";
import { EmptyState } from "./ui/EmptyState";

const navigation: readonly NavLink[] = [{ label: "Home", href: "/", current: true }];

// The first screen built here replaces this placeholder; keep the shell around it.
export function App() {
  return (
    <AppShell appName="App" navigation={navigation}>
      <h1>Home</h1>
      <EmptyState title="Nothing here yet">Screens appear here as they are built.</EmptyState>
    </AppShell>
  );
}
