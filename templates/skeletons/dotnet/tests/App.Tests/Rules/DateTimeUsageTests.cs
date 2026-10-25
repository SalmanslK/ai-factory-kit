using Xunit;

namespace App.Tests.Rules;

/// <summary>The time comes from an injected <see cref="TimeProvider"/>, and a timestamp carries its offset.</summary>
public sealed class DateTimeUsageTests
{
    /// <remarks>A direct clock read cannot be moved in a test, so an expiry or a "last updated" is tested only at whatever moment the suite runs.</remarks>
    [Fact]
    public void No_product_code_reads_the_clock_directly() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.ClockRead),
            "inject TimeProvider (timeProvider.GetUtcNow()) or pass the time in");

    /// <remarks>A <c>DateTime</c> read back from storage is often <c>Kind=Unspecified</c> and serialises with no offset, so a client cannot tell it is UTC.</remarks>
    [Fact]
    public void No_product_code_declares_a_DateTime() =>
        Rule.Holds(ProductSources.LinesMatching(ProductCodeRules.DateTimeDeclaration),
            "use DateTimeOffset for a moment in time, DateOnly or TimeOnly for a calendar date or a time of day");
}
