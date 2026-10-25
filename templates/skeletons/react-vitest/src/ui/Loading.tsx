// A labelled spinner; it shows only after 300ms (base.css), so a fast answer never flashes one.
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  );
}
