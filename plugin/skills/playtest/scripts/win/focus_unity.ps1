# Brings the Unity editor to the front. $args[0] (optional): only the editor whose window title contains it.
Add-Type @'
using System; using System.Runtime.InteropServices;
public class UwFocus {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
}
'@
$project = if ($args.Count -gt 0) { [string]$args[0] } else { "" }
$p = Get-Process Unity -ErrorAction SilentlyContinue |
     Where-Object { $_.MainWindowHandle -ne 0 -and ($project -eq "" -or $_.MainWindowTitle -like "*$project*") } |
     Select-Object -First 1
if ($p -eq $null) { if ($project) { "no Unity editor with '$project' in its title" } else { "Unity is not running" }; exit 1 }
if ([UwFocus]::IsIconic($p.MainWindowHandle)) { [UwFocus]::ShowWindowAsync($p.MainWindowHandle, 9) | Out-Null }
[UwFocus]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
"focused: $($p.MainWindowTitle)"
