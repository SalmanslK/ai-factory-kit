import { useState, type ReactNode } from "react";
import { Button } from "./Button";

export type NavLink = { label: string; href: string; current?: boolean };

type AppShellProps = {
  appName: string;
  navigation: readonly NavLink[];
  children: ReactNode;
};

// The layout every screen sits in: a skip link, the top bar, the side navigation (behind a Menu
// button on narrow screens) and the main region (docs/ui-standard.md §7).
export function AppShell({ appName, navigation, children }: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="shell-header">
        <Button
          variant="secondary"
          className="shell-menu-button"
          aria-expanded={menuOpen}
          aria-controls="side-navigation"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Menu
        </Button>
        <span className="shell-name">{appName}</span>
      </header>
      <nav id="side-navigation" className="shell-nav" aria-label="Main" data-open={menuOpen || undefined}>
        <ul>
          {navigation.map((link) => (
            <li key={link.href}>
              <a href={link.href} aria-current={link.current ? "page" : undefined}>
                {link.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" className="shell-main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
