using Xunit;

namespace App.Tests.Rules;

/// <summary>
/// The mechanical .NET rules in CLAUDE.md (Code rules, .NET), enforced on the product source
/// (<see cref="ProductSources"/>). Tests are exempt: they may block, pass a token that cannot cancel
/// and read the clock. The patterns are in <see cref="ProductCodeRules"/>, proven by
/// <see cref="ProductCodeRuleSelfTests"/>.
/// </summary>
/// <remarks>
/// An allow-list entry is a decision, made by a person: the file, how many, and why the rule's own
/// answer does not fit. The count makes a second use in a listed file fail too.
/// </remarks>
public sealed class ProductCodeRuleTests
{
    /// <summary>Where a null-forgiving <c>!</c> stands because no guard can replace it (a value a framework fills after construction).</summary>
    private static readonly Dictionary<string, (int Count, string Reason)> NullForgivingPermitted = new(StringComparer.Ordinal);

    /// <summary>Where catching every exception is right: a loop that must survive one bad item, or log-and-rethrow.</summary>
    private static readonly Dictionary<string, (int Count, string Reason)> BroadCatchPermitted = new(StringComparer.Ordinal);

    /// <summary>Where a <c>First</c> needs no ordering: the list's own order is the answer (the first invalid row submitted).</summary>
    private static readonly Dictionary<string, (int Count, string Reason)> UnorderedFirstPermitted = new(StringComparer.Ordinal);

    [Fact]
    public void The_rules_read_the_product_source() =>
        Assert.True(ProductSources.All.Count > 0, "no .cs files under " + Path.Combine(ProductSources.Root, "src") + " — every rule would pass");

    [Fact]
    public void Null_forgiving_operator_is_used_only_where_allow_listed() =>
        Rule.WithinAllowList(
            ProductSources.CountsPerFile(file => file.Code.Sum(line => ProductCodeRules.NullForgiving.Matches(line).Count)),
            NullForgivingPermitted,
            "no null-forgiving operator: prove the value with a guard — `x is { } value`, or `?? throw` where a null is a fault");

    [Fact]
    public void Exception_is_caught_broadly_only_where_allow_listed() =>
        Rule.WithinAllowList(
            ProductSources.CountsPerFile(file => file.Code.Count(ProductCodeRules.BroadCatch.IsMatch)),
            BroadCatchPermitted,
            "catch the specific exception you can turn into a result, or log and rethrow — never swallow every fault to keep a request alive");

    /// <remarks>"Ordered" means an <c>OrderBy</c> or <c>ThenBy</c> on the call's own chain. Unordered, a query returns whichever row the database reads first, which can change between runs.</remarks>
    [Fact]
    public void First_is_ordered_or_allow_listed() =>
        Rule.WithinAllowList(
            ProductSources.CountsPerFile(file => ProductCodeRules.UnorderedFirstCount(string.Join('\n', file.Code))),
            UnorderedFirstPermitted,
            "use Single/SingleOrDefault when at most one should match; where several may, order the query before First");

    [Fact]
    public void No_product_code_blocks_on_async() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.Blocking),
            "await instead — blocking a thread on a task starves the pool and can deadlock");

    [Fact]
    public void No_product_code_passes_a_token_that_cannot_cancel() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.UncancellableToken),
            "flow the caller's CancellationToken through — work the caller abandoned should stop");

    [Fact]
    public void Every_log_goes_through_a_LoggerMessage_method() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.DirectLogCall),
            "add a [LoggerMessage] method to a static partial *Log class beside the code, with its own event id");

    [Fact]
    public void No_product_code_uses_linq_query_syntax() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.QuerySyntax), "write LINQ in method syntax");

    [Fact]
    public void No_setting_is_read_by_a_string_key() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.ConfigurationByKey),
            "bind the section to a typed options class with ValidateOnStart, its section name a constant on that class");
}
