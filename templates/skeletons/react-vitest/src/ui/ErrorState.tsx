import type { ReactNode } from "react";
import { Button } from "./Button";

type ErrorStateProps = {
  title?: string;
  // What went wrong, whether anything was saved, and what to do — in plain words, never a code.
  children: ReactNode;
  onRetry?: () => void;
};

export function ErrorState({ title = "Something went wrong", children, onRetry }: ErrorStateProps) {
  return (
    <section className="state state-error" role="alert">
      <h2>{title}</h2>
      <p>{children}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </section>
  );
}
