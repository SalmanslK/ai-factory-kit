using Xunit;

namespace App.Tests.Rules;

/// <summary>How product types are declared and named.</summary>
public sealed class ConventionTests
{
    /// <summary>Where a class is designed to be inherited and is not abstract — rare; usually the base should be abstract.</summary>
    private static readonly Dictionary<string, (int Count, string Reason)> UnsealedPermitted = new(StringComparer.Ordinal);

    [Fact]
    public void Classes_are_sealed_static_or_abstract() =>
        Rule.WithinAllowList(
            ProductSources.CountsPerFile(file => file.Code.Count(ProductCodeRules.UnsealedClass.IsMatch)),
            UnsealedPermitted,
            "declare the class sealed (or static, or abstract when it is a base) — inheritance is a design decision, not a default");

    /// <remarks>These words name a bucket, and a bucket is where unrelated code accumulates.</remarks>
    [Fact]
    public void No_type_is_named_as_a_bucket() =>
        Rule.Holds(
            [.. ProductSources.All.SelectMany(file => file.Code
                .SelectMany(line => ProductCodeRules.TypeName.Matches(line))
                .Select(match => match.Groups[1].Value)
                .Where(name => ProductCodeRules.BucketName.IsMatch(name))
                .Select(name => $"{file.Relative}: {name}"))],
            "name the type for what it is (InvoiceTotals, ReceiptFormatter) — never Helper, Manager, Processor, Utility, DataService or CommonService");
}
