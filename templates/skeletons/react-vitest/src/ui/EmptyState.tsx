import type { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  // Why it is empty, and what to do next.
  children?: ReactNode;
  // The next step, when the person may take it — usually a Button.
  action?: ReactNode;
};

export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <section className="state">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </section>
  );
}
