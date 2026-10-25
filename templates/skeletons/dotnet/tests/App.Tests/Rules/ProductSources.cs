using System.Text.RegularExpressions;
using Xunit;

namespace App.Tests.Rules;

/// <summary>
/// Every hand-written source file under <c>src/</c>, read the way a source rule needs it: comment
/// lines blanked, and in <see cref="ProductSourceFile.Code"/> string literals emptied too, so a rule
/// matches what compiles rather than what a comment or a message says.
/// </summary>
/// <remarks>
/// Read as text because these rules are about call sites the compiler erases (<c>DateTime.UtcNow</c>
/// is a property read) and they cover every project under <c>src/</c> without a reference to each.
/// The blanking is line-based and simple on purpose: a false positive is answered with an allow-list
/// entry and its reason, or by narrowing the pattern with the case added to
/// <see cref="ProductCodeRuleSelfTests"/>. Tests are not product code and are not read.
/// </remarks>
internal static class ProductSources
{
    private static readonly Regex StringLiteral = new(@"@?\$*""(?:[^""\\]|\\.)*""", RegexOptions.None, TimeSpan.FromSeconds(1));
    private static readonly Regex InterpolationHole = new(@"(?<!\{)\{(?!\{)[^{}]*\}", RegexOptions.None, TimeSpan.FromSeconds(1));
    private static readonly string[] Generated = ["bin", "obj", "Migrations"];

    /// <summary>The folder that holds the solution: found by walking up, so moving the tests cannot make every rule pass on no files.</summary>
    public static string Root { get; } = FindRoot();

    public static IReadOnlyList<ProductSourceFile> All { get; } = Load();

    /// <summary>Each product line matching <paramref name="rule"/>, as <c>path:line</c>.</summary>
    public static string[] LinesMatching(Regex rule) =>
        [.. All.SelectMany(file => file.Code
            .Select((line, index) => (line, number: index + 1))
            .Where(entry => rule.IsMatch(entry.line))
            .Select(entry => $"{file.Relative}:{entry.number}"))];

    /// <summary>How many times <paramref name="count"/> finds something in each file that has any.</summary>
    public static Dictionary<string, int> CountsPerFile(Func<ProductSourceFile, int> count) =>
        All.Select(file => (file.Relative, Count: count(file)))
            .Where(file => file.Count > 0)
            .ToDictionary(file => file.Relative, file => file.Count, StringComparer.Ordinal);

    /// <summary>A line as <see cref="ProductSourceFile.Code"/> holds it: literals emptied (an interpolation's holes kept, they are code), trailing comment dropped.</summary>
    public static string CodeOf(string line)
    {
        var code = StringLiteral.Replace(line, literal => literal.Value.TrimStart('@').StartsWith('$')
            ? "\"\"" + string.Concat(InterpolationHole.Matches(literal.Value).Select(hole => hole.Value))
            : "\"\"");
        var comment = code.IndexOf("//", StringComparison.Ordinal);

        return comment < 0 ? code : code[..comment];
    }

    private static ProductSourceFile[] Load()
    {
        var src = Path.Combine(Root, "src");

        return [.. Directory.EnumerateFiles(src, "*.cs", SearchOption.AllDirectories)
            .Where(path => !Path.GetRelativePath(src, path).Split(Path.DirectorySeparatorChar).Any(Generated.Contains)
                           && !path.EndsWith(".Designer.cs", StringComparison.Ordinal))
            .Order(StringComparer.Ordinal)
            .Select(path =>
            {
                var text = File.ReadAllLines(path).Select(BlankCommentLine).ToArray();

                return new ProductSourceFile(Path.GetRelativePath(src, path).Replace('\\', '/'), text, [.. text.Select(CodeOf)]);
            })];
    }

    private static string BlankCommentLine(string line)
    {
        var trimmed = line.TrimStart();

        return trimmed.StartsWith("//", StringComparison.Ordinal) || trimmed.StartsWith("/*", StringComparison.Ordinal)
               || trimmed.StartsWith('*')
            ? string.Empty
            : line;
    }

    private static string FindRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);

        while (directory is not null && !directory.EnumerateFiles("*.sln*").Any())
        {
            directory = directory.Parent;
        }

        return directory?.FullName ?? throw new DirectoryNotFoundException("No solution file above " + AppContext.BaseDirectory);
    }
}

/// <summary>One source file: <see cref="Text"/> with comment lines blanked, <see cref="Code"/> with string literals emptied too.</summary>
internal sealed record ProductSourceFile(string Relative, IReadOnlyList<string> Text, IReadOnlyList<string> Code);

/// <summary>How every rule reports: the offenders, and what to do instead.</summary>
internal static class Rule
{
    public static void Holds(IReadOnlyCollection<string> offenders, string instead) =>
        Assert.True(offenders.Count == 0, $"{instead}: {string.Join(", ", offenders)}");

    /// <summary>
    /// Files over their allow-list (or not on it), and entries that allow more than the file has: a
    /// stale permission reads as precedent. Each entry is a count and the reason it is right.
    /// </summary>
    public static void WithinAllowList(Dictionary<string, int> found, Dictionary<string, (int Count, string Reason)> permitted, string instead)
    {
        Holds([.. found.Where(entry => entry.Value > permitted.GetValueOrDefault(entry.Key).Count)
            .Select(entry => $"{entry.Key} ({entry.Value})")], instead);
        Holds([.. permitted.Where(entry => found.GetValueOrDefault(entry.Key) < entry.Value.Count)
            .Select(entry => $"{entry.Key} (allows {entry.Value.Count}, has {found.GetValueOrDefault(entry.Key)})")],
            "lower or remove these allow-list entries");
    }
}
