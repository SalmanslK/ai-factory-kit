### .NET

The starter builds with nullable reference types on and warnings as errors *[enforced:
`Directory.Build.props`]*, and its test project carries rule tests that read every file under `src/`
as text: a rule below marked with a test's name fails `dotnet test` when new code breaks it. An
exception to a counted rule is an allow-list entry in that test — the file, how many, and why the
rule's own answer does not fit — and adding one is a person's decision. A change to a rule's pattern
adds the case that prompted it to `ProductCodeRuleSelfTests`, which proves every pattern catches a bad
sample and passes a good one.

Packages:

- **Package versions live in `Directory.Packages.props`** — a project names the package, never
  `Version=` *[enforced: `ProjectFileTests`]*. One version for every project; an upgrade is one line.
- **Prefer a maintained open-source library over writing our own**; write our own only when the
  surface is small and it stays behind one file. **A third-party library stays in one place**, behind
  our own type, so replacing it touches that place only. A new package is a person's decision.

Types and names:

- **`sealed` by default** — a class is `sealed`, `static`, or `abstract` when it is a base
  *[enforced: `ConventionTests`]*. `readonly` fields and `readonly` structs by default; records for
  immutable request and response shapes; `IReadOnlyCollection<T>` on the way out; explicit access
  modifiers; primary constructors where they read better.
- **No null-forgiving operator (`!`).** Prove the value: `x is { } value`, or `?? throw` where a null
  is a fault *[enforced: `ProductCodeRuleTests`]*.
- **Names say what the type is** — `InvoiceTotals`, `OrderReader`, `ReceiptFormatter`; never
  `Helper`, `Manager`, `Processor`, `Utility`, `DataService` or `CommonService` as a type name's last
  word: those name a bucket, and unrelated code collects in it *[enforced: `ConventionTests`]*.
- **No interface or base class without a second implementer in sight**, no wrapper method that
  renames a framework method one for one, no regions, no service locator, no static mutable state.
- **Rename unclear code rather than comment it.** No commented-out code; no `TODO` for a requirement
  already known — build it, or track it.

Behaviour:

- **Expected failures are results, faults are exceptions.** A not-found, a validation failure or a
  conflict returns the project's result type (`Result<T>`); an exception means something is broken.
- **Never catch broadly to keep a request alive.** Catch the specific exception you can turn into a
  result, or log and rethrow; a `catch (Exception)` or bare `catch` that is right (a loop that must
  survive one bad item) is an allow-list entry with its reason *[enforced: `ProductCodeRuleTests`]*.
- **`CancellationToken` flows all the way through** — no `CancellationToken.None`, `default(…)` or
  `new CancellationToken()` in product code. **Never block on async** — no `.Result`, `.Wait()` or
  `.GetAwaiter().GetResult()`; `await` it. Both *[enforced: `ProductCodeRuleTests`]*.
- **The time comes from an injected `TimeProvider`**, or is passed in — never `DateTime.UtcNow` or
  `DateTimeOffset.UtcNow`, so a test can set the clock. **Timestamps are `DateTimeOffset`**, a
  calendar date `DateOnly`: a `DateTime` loses its offset and a client cannot tell it is UTC. Both
  *[enforced: `DateTimeUsageTests`]*.
- **LINQ is method syntax**, never query syntax. **`Single`/`SingleOrDefault` over
  `First`/`FirstOrDefault`** when at most one element should match; `First` only where several may,
  and then order the query — unordered, the database returns whichever row it reads first. Both
  *[enforced: `ProductCodeRuleTests`]*.
- **Two writes that must succeed together go in one transaction**, written so it is safe to run
  again. **An email or an outbound call goes after the save has committed**, best-effort — log a
  failure, never fail the request for it — because it cannot be rolled back.

Settings and strings:

- **Settings are typed options**, bound from their section and checked with `ValidateOnStart` —
  never read by a string key (`configuration["…"]`, `GetValue<T>("…")`) *[enforced:
  `ProductCodeRuleTests`]*. The section name is a constant on the options class.
- **A placeholder setting starts with `REPLACE`**, so start-up validation can refuse it. **Never
  commit a real secret**; real values come from user secrets, the host's settings or a vault.
- **No magic strings or numbers.** A string that must match another — a route or endpoint name, a
  tag, a cache or lock key, a header, a message — is one constant beside the code that owns it,
  never a global `Constants` class and never a second copy.

Logging:

- **Log through a `[LoggerMessage]` method** in a `static partial` `*Log` class beside the code that
  logs, with its own event id — never a direct `logger.LogWarning(…)` call *[enforced:
  `ProductCodeRuleTests`]*. Its template is a compile-time constant, so a message is never an
  interpolated string and every value stays a structured field.
- **Never log** passwords, hashes, tokens, reset or invitation links, connection strings, or
  anything that identifies a customer.

Tests:

- xUnit, with its own `Assert`; no other assertion or mocking package is installed — adding one is a
  person's decision. A criterion's test carries `[Trait("AC", "<id>")]`.
- Tests are not product code: the rule tests do not read them, and a test may read the clock or
  pass a token that cannot cancel.
