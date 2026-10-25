### React and TypeScript

How a screen looks and behaves where the requirements and wireframes do not say is
[`docs/ui-standard.md`](docs/ui-standard.md) — follow it for every screen, and use the starter's
design system in `src/ui/` (tokens, base styles, shared components) before writing a new one.
`npm run lint` and `npm run typecheck` run at the factory's verify step and fail it.

Types:

- **TypeScript strict**, with no unused locals or parameters *[enforced: `tsconfig.json`,
  `npm run typecheck`]*.
- **No `any`** — `unknown` and a check that narrows it *[enforced: eslint
  `@typescript-eslint/no-explicit-any`]*. **No non-null `!`** — prove the value is there
  *[enforced: eslint `@typescript-eslint/no-non-null-assertion`]*. Lint warnings fail too
  *[enforced: `--max-warnings 0`]*.
- Props are a named `type`; a response from the API is typed once, where it is fetched.

Components:

- **Small, and named for what they show** — `InvoiceList`, `CustomerForm`, `OrderTotal`; never
  `Wrapper`, `Container`, `Manager` or `Helper`; a name ending in `Helper` or `Utils` fails the lint
  *[enforced: eslint `@typescript-eslint/naming-convention`]*. One exported component per file, the
  file named after it. A component that needs a scroll to read is two.
- **No business logic in a component.** Rules, calculations and formatting are plain functions
  beside the feature, tested on their own; a component renders and wires events to them.
- **Data fetching in one place.** Every call to the back end goes through one module
  (`src/api/`): its base address, headers, error handling and types live there. A screen gets its
  data through a hook in its feature (`useInvoices()`), never a `fetch` in a component.
- **Hooks follow the rules of hooks**, dependencies complete *[enforced: eslint
  `react-hooks/rules-of-hooks`, `react-hooks/exhaustive-deps` with `--max-warnings 0`]*.
- **Derive, do not copy.** Compute from props and state during render; `useEffect` is for
  talking to something outside React, never for keeping two pieces of state in step.
- List keys are stable ids, never the array index of a list that changes.
- Styles use the tokens in `src/ui/tokens.css` — no raw colour, pixel size or font in a
  component; a `style` attribute only for a value computed at run time.
- Dates, times and numbers are formatted with `Intl`, in the user's locale.

The rules every stack keeps, as React holds them:

- **The time comes from `now()` in `src/clock.ts`**, never `Date.now()` or `new Date()` in place;
  a test sets it with `vi.useFakeTimers()` and `vi.setSystemTime(...)` *[enforced: eslint
  `no-restricted-syntax`]*.
- **No `console.log` left in the product** — `console.warn` and `console.error` report a fault
  *[enforced: eslint `no-console`]*.
- **No empty `catch`** — handle the failure you expect, or let it reach the screen's error state
  *[enforced: eslint `no-empty`]*.

Less code, within the boundaries:

- **No abstraction before its second use.** A shared component appears when a second screen
  needs it, in `src/ui/`; until then it lives in its feature. Three plain lines beat a
  configurable component with flags.
- **No prop drilling beyond two levels without a reason** — pass `children`, or give that
  subtree a context. No global store until two distant screens share state.
- **Memoise only when measured** — `memo`, `useMemo`, `useCallback` with a note of what the
  profiler showed.
- State lives as low as it can; it moves up only when two siblings share it.
- A new package is a person's decision *[enforced: the guard asks — `package.json` and the lock are
  outside the build step's writes, so an unattended run cannot add one]*.

Tests:

- **Testing Library, by role and label** — `getByRole("button", { name: "Save changes" })`,
  `getByLabelText(...)`; never `getByTestId`, a class or the markup's shape. A test checks what a
  person sees and does, not a component's state or its hooks. A screen that cannot be found by
  role and name is not accessible, and its test says so.
- Assertions are Vitest's `expect`. `@testing-library/jest-dom` is not installed: read
  `getAttribute`, `textContent`, and the `description` option of `getByRole` instead.
- Interactions use `fireEvent`; `@testing-library/user-event` is not installed — adding it is a
  person's decision.
