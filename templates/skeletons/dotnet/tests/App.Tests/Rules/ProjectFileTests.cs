using System.Text.RegularExpressions;
using Xunit;

namespace App.Tests.Rules;

/// <summary>Package versions live in <c>Directory.Packages.props</c>, so every project uses the same one and an upgrade is one line.</summary>
public sealed class ProjectFileTests
{
    private static readonly Regex VersionedReference = new(@"<PackageReference\b[^>]*\bVersion\s*=", RegexOptions.IgnoreCase);

    [Fact]
    public void Versions_are_managed_centrally()
    {
        var props = Path.Combine(ProductSources.Root, "Directory.Packages.props");

        Assert.True(File.Exists(props) && File.ReadAllText(props).Contains("<ManagePackageVersionsCentrally>true<", StringComparison.Ordinal),
            "Directory.Packages.props must set ManagePackageVersionsCentrally to true");
    }

    [Fact]
    public void No_project_names_a_package_version() =>
        Rule.Holds(
            [.. Directory.EnumerateFiles(ProductSources.Root, "*.csproj", SearchOption.AllDirectories)
                .Where(path => VersionedReference.IsMatch(File.ReadAllText(path)))
                .Select(path => Path.GetRelativePath(ProductSources.Root, path).Replace('\\', '/'))
                .Order(StringComparer.Ordinal)],
            "drop Version= from the PackageReference and add a PackageVersion to Directory.Packages.props");
}
