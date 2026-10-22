# Waits up to $args[0] seconds (default 40) for Unity's "Scene(s) Have Been Modified" dialog and presses Cancel:
# the user's unsaved scene edits are kept and play still starts. Never press Save / Don't Save for the user.
$wait = if ($args.Count -gt 0) { [int]$args[0] } else { 40 }
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System; using System.Runtime.InteropServices;
public class UwClick {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(int f, int x, int y, int d, int e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
$A = [System.Windows.Automation.AutomationElement]
$root = $A::RootElement
$title = New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, "Scene(s) Have Been Modified")
$cancel = New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, "Cancel")
for ($i = 0; $i -lt $wait * 2; $i++) {
  $d = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $title)
  if ($d -ne $null) {
    $c = $d.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cancel)
    if ($c -eq $null) { "dialog found but no Cancel button"; exit 1 }
    try {
      $c.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()   # no mouse needed
    } catch {
      $r = $c.Current.BoundingRectangle
      [UwClick]::SetForegroundWindow([IntPtr]$d.Current.NativeWindowHandle) | Out-Null
      [UwClick]::SetCursorPos([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2)) | Out-Null
      Start-Sleep -Milliseconds 150
      [UwClick]::mouse_event(2, 0, 0, 0, 0); Start-Sleep -Milliseconds 60; [UwClick]::mouse_event(4, 0, 0, 0, 0)
    }
    "cancelled"
    exit 0
  }
  Start-Sleep -Milliseconds 500
}
"no dialog"
