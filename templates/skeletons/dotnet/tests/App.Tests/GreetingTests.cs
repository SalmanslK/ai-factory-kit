using App;
using Xunit;

namespace App.Tests;

// A criterion's test carries its id: [Trait("AC", "R-001.AC-1")].
public sealed class GreetingTests
{
    [Fact]
    public void Greets_by_name() => Assert.Equal("Hello, Ada", Greeting.For("Ada"));
}
