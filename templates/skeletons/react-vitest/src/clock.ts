// The one place the app reads the system clock: everything else asks here, so a test sets the time with
// vi.setSystemTime instead of waiting for it. The lint and the code-rules check refuse Date.now() and
// new Date() anywhere else.
export function now(): Date {
  return new Date();
}
