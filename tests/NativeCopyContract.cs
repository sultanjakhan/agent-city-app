using System;
using System.Reflection;
using AgentCityDesktop;
internal static class NativeCopyContract
{
    public static int Main()
    {
        var count = 0;
        foreach (var field in typeof(DesktopText).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            if (!field.IsLiteral || field.FieldType != typeof(string)) continue;
            var original = (string)field.GetRawConstantValue()!;
            if (DesktopText.ForLanguage(field.Name, "ru") != original ||
                DesktopText.ForLanguage(field.Name, "unsupported") != original)
                throw new Exception("Russian copy/fallback changed: " + field.Name);
            var english = DesktopText.ForLanguage(field.Name, "en");
            if (string.IsNullOrWhiteSpace(english)) throw new Exception("Missing English copy");
            foreach (var ch in english)
                if (ch >= '\u0400' && ch <= '\u04ff') throw new Exception("Russian copy in English lookup");
            count++;
        }
        if (count != 20) throw new Exception("Unexpected native copy key coverage");
        foreach (var locale in new[] { "ru", "en" })
        {
            try { DesktopText.ForLanguage("invalid", locale); }
            catch (ArgumentException) { continue; }
            throw new Exception("Unknown copy key did not fail explicitly");
        }
        Console.WriteLine("PASS native copy contract: 20 RU/EN keys, unchanged RU fallback, unknown-key rejection; host routing NOT tested");
        return 0;
    }
}
