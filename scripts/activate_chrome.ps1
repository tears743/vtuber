Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

$chrome = Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($chrome) {
    [Win32]::ShowWindow($chrome.MainWindowHandle, 9) | Out-Null  # SW_RESTORE
    [Win32]::SetForegroundWindow($chrome.MainWindowHandle) | Out-Null
    Write-Host "OK: Chrome activated"
} else {
    Write-Host "No Chrome window found"
}
