using System.Text.RegularExpressions;
using Xunit;

namespace App.Tests.Rules;

/// <summary>
/// Proves each pattern in <see cref="ProductCodeRules"/> fires on a violation and stays quiet on the
/// code it must allow.
/// </summary>
/// <remarks>
/// The rules only ever see product code that already obeys them, so on their own they pass whether
/// the pattern works or matches nothing. A pattern change that drops a case fails here. Each line is
/// read as the rules read it: through <see cref="ProductSources.CodeOf"/>.
/// </remarks>
public sealed class ProductCodeRuleSelfTests
{
    [Theory]
    [InlineData("var now = DateTime.UtcNow;", true)]
    [InlineData("var now = DateTimeOffset.UtcNow;", true)]
    [InlineData("var now = DateTimeOffset.Now;", true)]
    [InlineData("var today = DateTime.Today;", true)]
    [InlineData("var now = timeProvider.GetUtcNow();", false)]
    [InlineData("var text = \"DateTime.UtcNow\"; // DateTime.UtcNow", false)]
    public void Clock_read(string line, bool matches) => Check(ProductCodeRules.ClockRead, line, matches);

    [Theory]
    [InlineData("public DateTime CreatedAt { get; init; }", true)]
    [InlineData("public DateTime? PaidAt { get; init; }", true)]
    [InlineData("void Schedule(DateTime at)", true)]
    [InlineData("public DateTimeOffset CreatedAt { get; init; }", false)]
    [InlineData("public DateOnly DueDate { get; init; }", false)]
    public void DateTime_declaration(string line, bool matches) => Check(ProductCodeRules.DateTimeDeclaration, line, matches);

    [Theory]
    [InlineData("var value = task.Result;", true)]
    [InlineData("var id = task.Result.Id;", true)]
    [InlineData("var value = task.Result ?? fallback;", true)]
    [InlineData("if (task.Result is null)", true)]
    [InlineData("task.Wait();", true)]
    [InlineData("task.Wait(TimeSpan.FromSeconds(1));", true)]
    [InlineData("Task.WaitAll(first, second);", true)]
    [InlineData("var value = task.GetAwaiter().GetResult();", true)]
    [InlineData("await gate.WaitAsync(cancellationToken);", false)]
    [InlineData("var results = query.Results;", false)]
    [InlineData("return Result<long>.Success(id);", false)]
    [InlineData("return Result.Failure(error);", false)]
    [InlineData("Task<Result> Handle();", false)]
    [InlineData("var code = outcome.ResultCode;", false)]
    public void Blocking_on_async(string line, bool matches) => Check(ProductCodeRules.Blocking, line, matches);

    [Theory]
    [InlineData("await store.SaveAsync(order, CancellationToken.None);", true)]
    [InlineData("await store.SaveAsync(order, new CancellationToken());", true)]
    [InlineData("await store.SaveAsync(order, default(CancellationToken));", true)]
    [InlineData("await store.SaveAsync(order, cancellationToken);", false)]
    [InlineData("Task SaveAsync(Order order, CancellationToken cancellationToken = default);", false)]
    public void Uncancellable_token(string line, bool matches) => Check(ProductCodeRules.UncancellableToken, line, matches);

    [Theory]
    [InlineData("catch (Exception exception)", true)]
    [InlineData("catch (System.Exception)", true)]
    [InlineData("catch (global::System.Exception exception) when (IsTransient(exception))", true)]
    [InlineData("catch", true)]
    [InlineData("} catch { }", true)]
    [InlineData("catch when (attempt < 3)", true)]
    [InlineData("catch (IOException)", false)]
    [InlineData("catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)", false)]
    public void Broad_catch(string line, bool matches) => Check(ProductCodeRules.BroadCatch, line, matches);

    [Theory]
    [InlineData("logger.LogWarning(\"Order {OrderId} not found\", id);", true)]
    [InlineData("logger.LogError(exception, $\"Send to {address} failed\");", true)]
    [InlineData("logger.Log(LogLevel.Warning, \"Failed\");", true)]
    [InlineData("logger.OrderNotFound(id);", false)]
    [InlineData("private static partial void LogRetry(ILogger logger, int attempt);", false)]
    [InlineData("// logger.LogWarning(\"in a comment\");", false)]
    public void Direct_log_call(string line, bool matches) => Check(ProductCodeRules.DirectLogCall, line, matches);

    [Theory]
    [InlineData("var id = request.Id!.Value;", true)]
    [InlineData("Name = null!;", true)]
    [InlineData("var method = type.GetMethod(name)!;", true)]
    [InlineData("var item = items[0]!;", true)]
    [InlineData("var message = $\"Hello {name!}\";", true)]
    [InlineData("if (left != right)", false)]
    [InlineData("if (!flag)", false)]
    [InlineData("var open = orders.Where(order =>!order.Closed);", false)]
    [InlineData("return!flag;", false)]
    [InlineData("var message = \"Saved!\"; // done!", false)]
    public void Null_forgiving_operator(string line, bool matches) => Check(ProductCodeRules.NullForgiving, line, matches);

    [Theory]
    [InlineData("var open = from order in orders where order.IsOpen select order;", true)]
    [InlineData("var open = orders.Where(order => order.IsOpen);", false)]
    public void Query_syntax(string line, bool matches) => Check(ProductCodeRules.QuerySyntax, line, matches);

    [Theory]
    [InlineData("var url = builder.Configuration[\"Payments:Url\"];", true)]
    [InlineData("var url = configuration[\"Payments:Url\"];", true)]
    [InlineData("var retries = configuration.GetValue<int>(\"Retries\");", true)]
    [InlineData("var section = configuration.GetSection(\"Payments\");", true)]
    [InlineData("builder.Services.AddOptions<PaymentOptions>().BindConfiguration(PaymentOptions.Section).ValidateOnStart();", false)]
    [InlineData("var section = configuration.GetSection(PaymentOptions.Section);", false)]
    public void Configuration_by_key(string line, bool matches) => Check(ProductCodeRules.ConfigurationByKey, line, matches);

    [Theory]
    [InlineData("public class Invoice", true)]
    [InlineData("internal partial class Startup", true)]
    [InlineData("public record Invoice(long Id);", true)]
    [InlineData("public record class Invoice(long Id);", true)]
    [InlineData("public sealed class Invoice", false)]
    [InlineData("public static class InvoiceMappings", false)]
    [InlineData("public abstract class Entity", false)]
    [InlineData("public sealed record Invoice(long Id);", false)]
    [InlineData("public readonly record struct Money(decimal Amount);", false)]
    [InlineData("where T : class", false)]
    public void Unsealed_class(string line, bool matches) => Check(ProductCodeRules.UnsealedClass, line, matches);

    [Theory]
    [InlineData("StringHelper", true)]
    [InlineData("Helpers", true)]
    [InlineData("CacheManager", true)]
    [InlineData("ImportProcessor", true)]
    [InlineData("OrderDataService", true)]
    [InlineData("ManagerApproval", false)]
    [InlineData("InvoiceTotals", false)]
    public void Bucket_name(string name, bool matches) => Check(ProductCodeRules.BucketName, name, matches);

    [Theory]
    [InlineData("public sealed class StringHelper", "StringHelper")]
    [InlineData("internal interface IOrderReader", "IOrderReader")]
    [InlineData("public readonly record struct Money(decimal Amount);", "Money")]
    public void Type_name(string line, string name) =>
        Assert.Equal(name, ProductCodeRules.TypeName.Match(ProductSources.CodeOf(line)).Groups[1].Value);

    [Theory]
    [InlineData("orders.First(order => order.Id == id);", 1)]
    [InlineData("orders.OrderBy(order => order.Id).First();", 0)]
    [InlineData("orders.Where(order => order.IsOpen)\n    .OrderByDescending(order => order.PlacedAt)\n    .ThenBy(order => order.Id)\n    .FirstOrDefaultAsync(cancellationToken);", 0)]
    [InlineData("rows.OrderBy(row => row.Order).Select(row => row.Lines.FirstOrDefault()).ToList();", 1)]
    [InlineData("rows.Select(row => row.Lines.OrderBy(line => line.Number).First()).ToList();", 0)]
    [InlineData("items.OrderBy(item => item).ToList(); var first = items.First();", 1)]
    [InlineData("Use(a.OrderBy(x => x.Id).First(), b.First());", 1)]
    [InlineData("var pick = flag ? a.OrderBy(x => x.Id).First() : b.First();", 1)]
    [InlineData("var pick = a.OrderBy(x => x.Id).FirstOrDefault() ?? b.First();", 1)]
    [InlineData("var pick = a?.OrderBy(x => x.Id).First();", 0)]
    [InlineData("chars.Where(c => c == '(').OrderBy(c => c).First();", 0)]
    public void Unordered_First(string code, int expected) =>
        Assert.Equal(expected, ProductCodeRules.UnorderedFirstCount(string.Join('\n', code.Split('\n').Select(ProductSources.CodeOf))));

    private static void Check(Regex rule, string line, bool matches) =>
        Assert.True(rule.IsMatch(ProductSources.CodeOf(line)) == matches, $"'{line}' should {(matches ? "" : "not ")}match {rule}");
}
