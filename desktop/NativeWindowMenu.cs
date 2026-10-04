using System.Runtime.InteropServices;

namespace AgentCityDesktop;

// Use the title-bar icon menu, leaving the application content free of a second brand row.
internal sealed class NativeWindowMenu(nint window, params ToolStripMenuItem[] items)
{
    private const uint ByCommand = 0, String = 0, Separator = 0x800, Disabled = 3;
    private readonly nint menu = GetSystemMenu(window, false);
    private const uint FirstCommand = 0xC000;

    public void Install()
    {
        if (menu == 0) return;
        AppendMenu(menu, Separator, 0, null);
        for (var index = 0; index < items.Length; index++)
            AppendMenu(menu, String, FirstCommand + (uint)index * 16, items[index].Text);
        Refresh();
    }

    public void Refresh()
    {
        if (menu == 0) return;
        for (var index = 0; index < items.Length; index++)
        {
            var command = FirstCommand + (uint)index * 16;
            ModifyMenu(menu, command, ByCommand | String, command, items[index].Text ?? "");
            EnableMenuItem(menu, command, ByCommand | (items[index].Enabled ? 0 : Disabled));
        }
    }

    public bool Dispatch(nint command)
    {
        var id = unchecked((uint)command.ToInt64()) & 0xFFF0;
        if (id < FirstCommand || id >= FirstCommand + items.Length * 16) return false;
        var item = items[(id - FirstCommand) / 16];
        if (item.Enabled) item.PerformClick();
        return true;
    }

    public static void Reveal(nint ownedWindow) => ShowWindow(ownedWindow, 5);
    [DllImport("user32.dll")] private static extern bool ShowWindow(nint window, int command);
    [DllImport("user32.dll")] private static extern nint GetSystemMenu(nint window, bool revert);
    [DllImport("user32.dll", EntryPoint = "AppendMenuW", CharSet = CharSet.Unicode)]
    private static extern bool AppendMenu(nint menu, uint flags, uint id, string? text);
    [DllImport("user32.dll", EntryPoint = "ModifyMenuW", CharSet = CharSet.Unicode)]
    private static extern bool ModifyMenu(nint menu, uint position, uint flags, uint id, string text);
    [DllImport("user32.dll")] private static extern uint EnableMenuItem(nint menu, uint id, uint flags);
}
