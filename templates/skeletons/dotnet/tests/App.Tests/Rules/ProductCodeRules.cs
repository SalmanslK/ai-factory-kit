using System.Text;
using System.Text.RegularExpressions;

namespace App.Tests.Rules;

/// <summary>
/// The patterns the source rules match, in one place so <see cref="ProductCodeRuleSelfTests"/> can
/// prove each fires on a violation and stays quiet on the code it must allow.
/// </summary>
/// <remarks>
/// A rule that matches nothing passes as green as one that holds. Every change to a pattern adds
/// the case that motivated it to the self-tests. Patterns run on
/// <see cref="ProductSourceFile.Code"/> lines, where literals and comments are already gone.
/// </remarks>
internal static class ProductCodeRules
{
    public static readonly Regex ClockRead = new(@"\b(?:DateTime|DateTimeOffset)\.(?:UtcNow|Now|Today)\b");

    /// <summary>Something declared as a <c>DateTime</c> — a property, field, parameter, local or return type.</summary>
    /// <remarks>Known limit: a <c>DateTime</c> as a generic argument (<c>List&lt;DateTime&gt;</c>) is not seen.</remarks>
    public static readonly Regex DateTimeDeclaration = new(@"\bDateTime\??\s+@?[A-Za-z_]");

    /// <summary>
    /// <c>.Result</c> read off a task, <c>.Wait()</c>, <c>.WaitAll(</c>, <c>.WaitAny(</c> and
    /// <c>.GetAwaiter().GetResult()</c>. Not a generic <c>Result&lt;T&gt;</c>, the static
    /// <c>Result.Success</c> / <c>Result.Failure</c>, a declaration (<c>Result name</c>) or a longer
    /// name (<c>Results</c>). Known limit: a property of our own named <c>Result</c> is flagged.
    /// </summary>
    public static readonly Regex Blocking = new(
        @"\.Result\b(?![<>])(?!\s*\.\s*(?:Success|Failure)\b)(?!\s+(?!(?:is|as|and|or|switch)\b)[A-Za-z_@])"
        + @"|\.Wait(?:All|Any)?\s*\("
        + @"|\.GetAwaiter\(\)\s*\.GetResult\(\)");

    /// <summary>A token that can never cancel, however it is spelled. Known limit: an omitted optional token.</summary>
    public static readonly Regex UncancellableToken = new(
        @"\bCancellationToken\.None\b|\bnew\s+CancellationToken\s*\(\s*(?:false)?\s*\)|\bdefault\s*\(\s*CancellationToken\s*\)");

    /// <summary>A catch that takes every exception: <c>catch (Exception)</c> in any spelling, and a bare <c>catch</c>, with or without <c>when</c>.</summary>
    public static readonly Regex BroadCatch = new(@"\bcatch\s*(?:\{|$|when\b|\(\s*(?:global::)?(?:System\.)?Exception\b)");

    /// <summary>
    /// A log written straight onto an <c>ILogger</c> (<c>LogWarning(</c>, <c>Log(</c> …) rather than
    /// through a <c>[LoggerMessage]</c> method, whose template is a compile-time constant — so it is
    /// never interpolated — with a level and an event id. The generated methods are in <c>obj/</c>,
    /// which is not read; a method that merely starts with <c>Log</c> does not match.
    /// </summary>
    public static readonly Regex DirectLogCall = new(@"\.Log(?:Trace|Debug|Information|Warning|Error|Critical)?\s*(?:<[^>]*>)?\s*\(");

    /// <summary>
    /// The null-forgiving <c>!</c>: postfix, straight after an identifier, <c>)</c>, <c>]</c> or a
    /// generic's <c>&gt;</c>, and not the start of <c>!=</c>. A keyword written against a negation
    /// (<c>return!flag</c>) and a lambda arrow (<c>=&gt;!flag</c>) are not it.
    /// </summary>
    public static readonly Regex NullForgiving = new(
        @"(?:\w(?<!\b(?:return|throw|await|yield|case|when|is|in|and|or|not))|[)\]]|(?<!=)>)!(?!=)");

    public static readonly Regex QuerySyntax = new(@"\bfrom\s+(?:\w+\s+)?\w+\s+in\s+\S");

    /// <summary>A setting read by a string key instead of bound to typed options.</summary>
    public static readonly Regex ConfigurationByKey = new(@"\b\w*[Cc]onfiguration\s*\[|\.GetValue\s*<|\.GetSection\s*\(\s*""""");

    /// <summary>A class or record declared without <c>sealed</c>, <c>static</c> or <c>abstract</c>. A <c>record struct</c> cannot be sealed and is not matched.</summary>
    public static readonly Regex UnsealedClass = new(
        @"^\s*(?:(?:public|internal|protected|private|file|partial|unsafe|new)\s+)*(?:class|record(?!\s+struct\b)(?:\s+class)?)\s+@?[A-Za-z_]");

    /// <summary>A type declaration's name, for <see cref="BucketName"/>.</summary>
    public static readonly Regex TypeName = new(@"\b(?:record\s+(?:class|struct)|class|record|struct|interface|enum)\s+@?([A-Za-z_]\w*)");

    /// <summary>A name that says "a place to put things" instead of what the type is. Matched at the end only: <c>ManagerApproval</c> is fine.</summary>
    public static readonly Regex BucketName = new(@"(?:Helpers?|Manager|Processor|Utility|Utilities|DataService|CommonService)$");

    private static readonly Regex FirstCall = new(@"\.First(?:OrDefault)?(?:Async)?\s*[(<]");
    private static readonly Regex Ordering = new(@"\.(?:OrderBy|OrderByDescending|ThenBy|ThenByDescending)\s*\(");
    private static readonly Regex CharLiteral = new(@"'(?:[^'\\]|\\.)'");

    /// <summary>How many <c>First</c> calls in <paramref name="code"/> (literals emptied) have no ordering on their own chain.</summary>
    public static int UnorderedFirstCount(string code)
    {
        var bare = CharLiteral.Replace(code, "''");

        return FirstCall.Matches(bare).Count(call => !Ordering.IsMatch(ChainBefore(bare, call.Index)));
    }

    /// <summary>
    /// The receiver chain a call at <paramref name="index"/> is made on, argument lists dropped.
    /// </summary>
    /// <remarks>
    /// Walks back at the call's own nesting level and stops at an unmatched <c>(</c> or <c>[</c> —
    /// the call is inside an argument, such as a lambda, and an <c>OrderBy</c> outside does not order
    /// it — or where its expression starts (<see cref="EndsExpression"/>).
    /// </remarks>
    public static string ChainBefore(string code, int index)
    {
        var reversed = new StringBuilder();
        var depth = 0;

        for (var position = index - 1; position >= 0; position--)
        {
            var character = code[position];

            if (character is ')' or ']')
            {
                if (depth++ == 0)
                {
                    reversed.Append(character);
                }
            }
            else if (character is '(' or '[')
            {
                if (depth == 0)
                {
                    break;
                }

                if (--depth == 0)
                {
                    reversed.Append(character);
                }
            }
            else if (depth == 0)
            {
                if (EndsExpression(code, position))
                {
                    break;
                }

                reversed.Append(character);
            }
        }

        var chain = reversed.ToString().ToCharArray();
        Array.Reverse(chain);

        return new string(chain);
    }

    /// <summary>
    /// A statement end, a separator, a ternary's <c>?</c> or <c>:</c>, any <c>=</c> (assignment,
    /// comparison, lambda arrow), <c>&amp;&amp;</c> or <c>||</c>: each starts a new expression, and an
    /// <c>OrderBy</c> before it orders something else. <c>?.</c> and <c>?[</c> stay in the chain.
    /// </summary>
    private static bool EndsExpression(string code, int position)
    {
        var next = position + 1 < code.Length ? code[position + 1] : '\0';

        return code[position] switch
        {
            ';' or '{' or '}' or ',' or ':' or '=' or '&' or '|' => true,
            '?' => next is not ('.' or '['),
            _ => false,
        };
    }
}
