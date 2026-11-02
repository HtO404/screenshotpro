param(
  [Parameter(Mandatory=$true)][string]$Exe,
  [Parameter(Mandatory=$true)][string]$WorkDir,
  [int]$WaitSec = 6,
  [int]$SettleMs = 800,
  [int]$CaptureRounds = 3,
  [int]$RetryMs = 700,
  [double]$DiffThreshold = 3.0,
  [int]$DiffSampleStep = 6
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Na {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint nFlags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool UpdateWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr hWnd, uint flags);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, System.Text.StringBuilder s, int n);
  public static readonly IntPtr TOPMOST = new IntPtr(-1);
  public static readonly IntPtr NOTOPMOST = new IntPtr(-2);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hWnd);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr hWnd, int attr, out RECT pvAttribute, int cbAttribute);
}
'@

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

function Get-TopWindowAt([int]$x, [int]$y) {
  # Which top-level window owns this screen point. Used to explain a failed cross-check:
  # if it is not our window the screen simply does not show the app (locked desktop, or
  # something on top of it), and no capture setting can fix that.
  $p = New-Object 'Na+POINT'
  $p.X = $x
  $p.Y = $y
  $h = [Na]::WindowFromPoint($p)
  $root = [IntPtr]::Zero
  try { $root = [Na]::GetAncestor($h, 2) } catch { $root = $h }
  if ($root -eq [IntPtr]::Zero) { $root = $h }
  $owner = [uint32]0
  [void][Na]::GetWindowThreadProcessId($root, [ref]$owner)
  $sb = New-Object System.Text.StringBuilder 512
  [void][Na]::GetWindowTextW($root, $sb, 512)
  $pn = ''
  try { $pn = (Get-Process -Id ([int]$owner) -ErrorAction SilentlyContinue).ProcessName } catch { $pn = '' }
  return [ordered]@{ hwnd = $root.ToInt64(); pid = [int]$owner; proc = $pn; title = $sb.ToString() }
}

function Get-SampledMeanAbsDiff($bmpA, $bmpB, [int]$step) {
  # Sampled mean absolute difference (0..255) between two 24bpp bitmaps, one sample every
  # $step-th pixel on both axes. It only decides whether the screen has finished repainting;
  # the authoritative cross-check is numpy in measure_win.py.
  $w = [Math]::Min($bmpA.Width, $bmpB.Width)
  $h = [Math]::Min($bmpA.Height, $bmpB.Height)
  if (($w -le 0) -or ($h -le 0)) { return -1.0 }
  $ra = New-Object System.Drawing.Rectangle(0, 0, $bmpA.Width, $bmpA.Height)
  $rb = New-Object System.Drawing.Rectangle(0, 0, $bmpB.Width, $bmpB.Height)
  $da = $bmpA.LockBits($ra, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $db = $bmpB.LockBits($rb, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $sum = [double]0
  $n = [long]0
  try {
    $sa = $da.Stride
    $sb = $db.Stride
    $bufA = New-Object byte[] ($sa * $bmpA.Height)
    $bufB = New-Object byte[] ($sb * $bmpB.Height)
    [System.Runtime.InteropServices.Marshal]::Copy($da.Scan0, $bufA, 0, $bufA.Length)
    [System.Runtime.InteropServices.Marshal]::Copy($db.Scan0, $bufB, 0, $bufB.Length)
    for ($y = 0; $y -lt $h; $y = $y + $step) {
      $oa = $y * $sa
      $ob = $y * $sb
      for ($x = 0; $x -lt $w; $x = $x + $step) {
        $ia = $oa + $x * 3
        $ib = $ob + $x * 3
        $sum = $sum + [Math]::Abs([int]$bufA[$ia] - [int]$bufB[$ib])
        $sum = $sum + [Math]::Abs([int]$bufA[$ia + 1] - [int]$bufB[$ib + 1])
        $sum = $sum + [Math]::Abs([int]$bufA[$ia + 2] - [int]$bufB[$ib + 2])
        $n = $n + 3
      }
    }
  }
  finally {
    $bmpA.UnlockBits($da)
    $bmpB.UnlockBits($db)
  }
  if ($n -eq 0) { return -1.0 }
  return ($sum / $n)
}


$meta = [ordered]@{}
$meta.exe = $Exe
$meta.workdir = $WorkDir
$meta.capture_at = (Get-Date).ToString('o')
$meta.dpi_aware = [bool][Na]::SetProcessDPIAware()
$meta.screen_w = [Na]::GetSystemMetrics(0)
$meta.screen_h = [Na]::GetSystemMetrics(1)
$vx = [Na]::GetSystemMetrics(76); $vy = [Na]::GetSystemMetrics(77)
$vw = [Na]::GetSystemMetrics(78); $vh = [Na]::GetSystemMetrics(79)
$meta.virtual_screen = [ordered]@{ x = $vx; y = $vy; w = $vw; h = $vh }
$meta.window_found = $false
$meta.moved = $false
$meta.printwindow_flags = 0
$meta.printwindow_ok = $false
$meta.bitblt_ok = $false
$meta.killed = $false
$meta.controls_count = 0
$meta.controls_skipped_empty = 0

$proc = $null
try {
  $t0 = Get-Date
  $proc = Start-Process -FilePath $Exe -PassThru
  $meta.pid = $proc.Id
  Write-Output ("LAUNCHED pid=" + $proc.Id)

  $root = [System.Windows.Automation.AutomationElement]::RootElement
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$proc.Id)
  $win = $null
  $deadline = (Get-Date).AddSeconds(15)
  while ((Get-Date) -lt $deadline) {
    $cand = $null
    try { $cand = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond) } catch { $cand = $null }
    if ($cand -ne $null) {
      $cb = $cand.Current.BoundingRectangle
      if (-not [double]::IsNaN($cb.Width) -and $cb.Width -ge 200 -and $cb.Height -ge 200) { $win = $cand; break }
    }
    Start-Sleep -Milliseconds 200
  }
  if ($win -eq $null) { $meta.error = 'no-top-level-window'; throw 'no-top-level-window' }

  $meta.window_found = $true
  $meta.window_wait_ms = [int]((Get-Date) - $t0).TotalMilliseconds
  Write-Output ("WINDOW found after " + $meta.window_wait_ms + " ms")

  $remain = ($WaitSec * 1000) - ((Get-Date) - $t0).TotalMilliseconds
  if ($remain -gt 0) { Start-Sleep -Milliseconds ([int]$remain) }
  Start-Sleep -Milliseconds 800

  $hwnd = [System.IntPtr]::Zero
  try { $hwnd = [System.IntPtr]$win.Current.NativeWindowHandle } catch { $hwnd = [System.IntPtr]::Zero }
  if ($hwnd -eq [System.IntPtr]::Zero) { $hwnd = $proc.MainWindowHandle }
  $meta.hwnd = $hwnd.ToInt64()

  $r = New-Object 'Na+RECT'
  [void][Na]::GetWindowRect($hwnd, [ref]$r)
  $rw = $r.Right - $r.Left
  $rh = $r.Bottom - $r.Top
  Write-Output ("GETWINDOWRECT0 " + $r.Left + "," + $r.Top + " " + $rw + "x" + $rh)

  $wa = [System.Windows.Forms.SystemInformation]::WorkingArea
  $meta.work_area = [ordered]@{ x = $wa.X; y = $wa.Y; w = $wa.Width; h = $wa.Height }
  $fullyInside = ($r.Left -ge $wa.Left) -and ($r.Top -ge $wa.Top) -and ($r.Right -le $wa.Right) -and ($r.Bottom -le $wa.Bottom)
  if (-not $fullyInside) {
    $before = "" + $r.Left + "," + $r.Top
    [void][Na]::SetWindowPos($hwnd, [System.IntPtr]::Zero, $wa.Left, $wa.Top, 0, 0, 0x0001 -bor 0x0004)
    Start-Sleep -Milliseconds 600
    [void][Na]::GetWindowRect($hwnd, [ref]$r)
    $rw = $r.Right - $r.Left
    $rh = $r.Bottom - $r.Top
    $meta.moved = $true
    Write-Output ("MOVED window " + $before + " -> " + $r.Left + "," + $r.Top + " workarea=" + $wa.Width + "x" + $wa.Height)
  } else {
    Write-Output ("KEPT window " + $r.Left + "," + $r.Top + " (already inside work area)")
  }

  $gwr = [ordered]@{ x = $r.Left; y = $r.Top; w = $rw; h = $rh }
  $meta.getwindowrect = $gwr
  Write-Output ("GETWINDOWRECT " + $r.Left + "," + $r.Top + " " + $rw + "x" + $rh)

  $fbLeft = $r.Left; $fbTop = $r.Top; $fbW = $rw; $fbH = $rh; $dwmOk = $false
  $fr = New-Object 'Na+RECT'
  $hrc = [Na]::DwmGetWindowAttribute($hwnd, 9, [ref]$fr, 16)
  if ($hrc -eq 0) {
    $fw = $fr.Right - $fr.Left
    $fh = $fr.Bottom - $fr.Top
    if ($fw -gt 0 -and $fh -gt 0 -and $fr.Left -ge $r.Left -and $fr.Top -ge $r.Top -and $fr.Right -le $r.Right -and $fr.Bottom -le $r.Bottom) {
      $fbLeft = $fr.Left; $fbTop = $fr.Top; $fbW = $fw; $fbH = $fh; $dwmOk = $true
    }
  }
  $insetL = $fbLeft - $r.Left
  $insetT = $fbTop - $r.Top
  $insetR = $r.Right - ($fbLeft + $fbW)
  $insetB = $r.Bottom - ($fbTop + $fbH)
  $meta.dwm_extended_frame = [ordered]@{ x = $fbLeft; y = $fbTop; w = $fbW; h = $fbH; hresult = $hrc; used = $dwmOk }
  $meta.frame_inset = [ordered]@{ left = $insetL; top = $insetT; right = $insetR; bottom = $insetB }
  $meta.window_rect = [ordered]@{ x = $fbLeft; y = $fbTop; w = $fbW; h = $fbH }
  Write-Output ("DWMFRAME " + $fbLeft + "," + $fbTop + " " + $fbW + "x" + $fbH + " used=" + $dwmOk + " inset(L,T,R,B)=" + $insetL + "," + $insetT + "," + $insetR + "," + $insetB)

  $ub = $win.Current.BoundingRectangle
  $meta.uia_top_rect = [ordered]@{ x = [int]$ub.X; y = [int]$ub.Y; w = [int]$ub.Width; h = [int]$ub.Height }
  $meta.window_title = $win.Current.Name
  try { $meta.dpi_for_window = [Na]::GetDpiForWindow($hwnd) } catch { $meta.dpi_for_window = 0 }
  Write-Output ("UIARECT " + [int]$ub.X + "," + [int]$ub.Y + " " + [int]$ub.Width + "x" + [int]$ub.Height)
  Write-Output ("DPI_AWARE=" + $meta.dpi_aware + " DPI_FOR_WINDOW=" + $meta.dpi_for_window + " SCREEN=" + $meta.screen_w + "x" + $meta.screen_h + " VIRTUAL=" + $vw + "x" + $vh)

  if ($fbW -le 0 -or $fbH -le 0) { $meta.error = 'empty-window-rect'; throw 'empty-window-rect' }

  # ---- capture rounds: raise -> settle -> PrintWindow + BitBlt + sampled diff ----
  # SetWindowPos can move the app from a secondary monitor onto the primary work area. The
  # screen is not repainted at that instant, so a BitBlt taken right after the move captures
  # whatever was there before (observed: mean_abs_diff ~98 against a correct PrintWindow).
  # Each round therefore re-raises the window, waits for it to be non-minimised with a stable
  # rect, sleeps SettleMs, then captures and compares the two images itself. Rounds stop at the
  # first accept; measure_win.py still runs the authoritative numpy check and stays fail-closed.
  $sx = [Math]::Max($vx, $fbLeft)
  $sy = [Math]::Max($vy, $fbTop)
  $sx2 = [Math]::Min($vx + $vw, $fbLeft + $fbW)
  $sy2 = [Math]::Min($vy + $vh, $fbTop + $fbH)
  $ow = [Math]::Max(0, $sx2 - $sx)
  $oh = [Math]::Max(0, $sy2 - $sy)
  $meta.overlap = [ordered]@{ x = ($sx - $fbLeft); y = ($sy - $fbTop); w = $ow; h = $oh }
  Write-Output ("OVERLAP " + ($sx - $fbLeft) + "," + ($sy - $fbTop) + " " + $ow + "x" + $oh)

  $pwPath = Join-Path $WorkDir 'printwindow.png'
  $bbPath = Join-Path $WorkDir 'bitblt.png'
  $meta.capture_rounds = 0
  $meta.capture_accepted = $false
  $meta.capture_round_log = @()
  $accepted = $false
  $round = 0
  while ($round -lt $CaptureRounds) {
    $round = $round + 1
    $tRound = Get-Date
    $fg = $false
    try { [void][Na]::ShowWindow($hwnd, 9) } catch {}
    try { [void][Na]::SetWindowPos($hwnd, [Na]::TOPMOST, 0, 0, 0, 0, 0x0001 -bor 0x0002) } catch {}
    try { $fg = [bool][Na]::SetForegroundWindow($hwnd) } catch {}
    try { [void][Na]::BringWindowToTop($hwnd) } catch {}
    try { [void][Na]::UpdateWindow($hwnd) } catch {}
    $tStable = Get-Date
    $lastKey = ''
    while (((Get-Date) - $tStable).TotalMilliseconds -lt 3000) {
      $rr = New-Object 'Na+RECT'
      [void][Na]::GetWindowRect($hwnd, [ref]$rr)
      $key = "" + $rr.Left + "," + $rr.Top + "," + $rr.Right + "," + $rr.Bottom
      $iconic = $false
      try { $iconic = [bool][Na]::IsIconic($hwnd) } catch {}
      if ((-not $iconic) -and ($key -eq $lastKey)) { break }
      $lastKey = $key
      Start-Sleep -Milliseconds 120
    }
    if ($SettleMs -gt 0) { Start-Sleep -Milliseconds $SettleMs }
    $waitedMs = [int]((Get-Date) - $tRound).TotalMilliseconds
    $probeX = [Math]::Min([Math]::Max($fbLeft + [int]($fbW / 2), 0), $meta.screen_w - 1)
    $probeY = [Math]::Min([Math]::Max($fbTop + [int]($fbH / 2), 0), $meta.screen_h - 1)
    $top = Get-TopWindowAt $probeX $probeY
    $onTop = ($top.hwnd -eq $hwnd.ToInt64())
    $topDesc = $top.proc + '(' + $top.pid + ')'
    $meta.capture_on_top = $onTop
    $meta.capture_top_window = $top

    $bmp = New-Object System.Drawing.Bitmap($rw, $rh, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(255, 255, 0, 255))
    $hdc = $g.GetHdc()
    $ok = [Na]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    $flagsUsed = 2
    if (-not $ok) {
      $hdc = $g.GetHdc()
      $ok = [Na]::PrintWindow($hwnd, $hdc, 0)
      $g.ReleaseHdc($hdc)
      $flagsUsed = 0
    }
    $g.Dispose()
    $meta.printwindow_flags = $flagsUsed
    $meta.printwindow_ok = [bool]$ok

    $pwShot = $bmp
    if (($insetL -ne 0) -or ($insetT -ne 0) -or ($insetR -ne 0) -or ($insetB -ne 0)) {
      $srcRect = New-Object System.Drawing.Rectangle($insetL, $insetT, $fbW, $fbH)
      $pwShot = $bmp.Clone($srcRect, $bmp.PixelFormat)
    }
    $pwShot.Save($pwPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $meta.printwindow_size = [ordered]@{ w = $pwShot.Width; h = $pwShot.Height }

    $haveBb = $false
    $diff = -1.0
    if ($ow -gt 0 -and $oh -gt 0) {
      $bb = New-Object System.Drawing.Bitmap($ow, $oh, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
      $gb = [System.Drawing.Graphics]::FromImage($bb)
      $gb.CopyFromScreen($sx, $sy, 0, 0, (New-Object System.Drawing.Size($ow, $oh)), [System.Drawing.CopyPixelOperation]::SourceCopy)
      $gb.Dispose()
      $bb.Save($bbPath, [System.Drawing.Imaging.ImageFormat]::Png)
      $meta.bitblt_ok = $true
      $ovRect = New-Object System.Drawing.Rectangle(($sx - $fbLeft), ($sy - $fbTop), $ow, $oh)
      $pwOv = $pwShot.Clone($ovRect, $pwShot.PixelFormat)
      $diff = Get-SampledMeanAbsDiff $pwOv $bb $DiffSampleStep
      $pwOv.Dispose()
      $bb.Dispose()
      $haveBb = $true
    }

    if ($pwShot -ne $bmp) { $pwShot.Dispose() }
    $bmp.Dispose()

    $meta.capture_rounds = $round
    $meta.capture_round_log = @($meta.capture_round_log) + @([ordered]@{ round = $round; foreground = $fg; wait_ms = $waitedMs; diff = [Math]::Round($diff, 4); on_top = $onTop; top = $topDesc })
    if ($haveBb) {
      Write-Output ("CAPTURE round=" + $round + "/" + $CaptureRounds + " fg=" + $fg + " wait_ms=" + $waitedMs + " diff=" + [Math]::Round($diff, 4) + " threshold=" + $DiffThreshold + " on_top=" + $onTop + " top=" + $topDesc)
    } else {
      Write-Output ("CAPTURE round=" + $round + "/" + $CaptureRounds + " fg=" + $fg + " wait_ms=" + $waitedMs + " diff=n/a (no on-screen area) on_top=" + $onTop + " top=" + $topDesc)
    }
    if ($haveBb -and ($diff -ge 0) -and ($diff -lt $DiffThreshold)) { $accepted = $true; break }
    if ($round -lt $CaptureRounds) {
      Write-Output ("CAPTURE retry in " + $RetryMs + " ms")
      Start-Sleep -Milliseconds $RetryMs
    }
  }
  try { [void][Na]::SetWindowPos($hwnd, [Na]::NOTOPMOST, 0, 0, 0, 0, 0x0001 -bor 0x0002) } catch {}
  $meta.capture_accepted = $accepted
  Write-Output ("PRINTWINDOW flags=" + $meta.printwindow_flags + " ok=" + $meta.printwindow_ok)
  Write-Output ("PRINTWINDOW saved " + $meta.printwindow_size.w + "x" + $meta.printwindow_size.h)
  if ($meta.bitblt_ok) {
    Write-Output ("BITBLT saved " + $ow + "x" + $oh + " (accepted=" + $accepted + ", rounds=" + $meta.capture_rounds + ")")
  } else {
    Write-Output "BITBLT skipped (no on-screen area)"
  }

  $walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
  $script:rows = New-Object System.Collections.ArrayList
  $script:skipped = 0
  $script:MaxRows = 400
  $script:MaxDepth = 6

  function Dump-Children($parentEl, $depth, $parentPath) {
    if ($depth -gt $script:MaxDepth) { return }
    if ($script:rows.Count -ge $script:MaxRows) { return }
    $counts = @{}
    $child = $null
    try { $child = $walker.GetFirstChild($parentEl) } catch { $child = $null }
    while ($child -ne $null) {
      if ($script:rows.Count -ge $script:MaxRows) { return }
      $ctName = 'Unknown'
      $nm = ''
      $aid = ''
      try { $ctName = $child.Current.ControlType.ProgrammaticName.Replace('ControlType.', '') } catch {}
      try { $nm = [string]$child.Current.Name } catch { $nm = '' }
      try { $aid = [string]$child.Current.AutomationId } catch { $aid = '' }
      if (-not $counts.ContainsKey($ctName)) { $counts[$ctName] = 0 }
      $counts[$ctName] = $counts[$ctName] + 1
      $p = $parentPath + '/' + $ctName + '[' + $counts[$ctName] + ']'
      $b = $child.Current.BoundingRectangle
      $bw = 0; $bh = 0; $bx = 0; $by = 0; $finite = $false
      if (-not [double]::IsNaN($b.Width) -and -not [double]::IsInfinity($b.Width) -and -not [double]::IsNaN($b.X)) {
        $finite = $true
        $bx = [int][Math]::Round($b.X); $by = [int][Math]::Round($b.Y)
        $bw = [int][Math]::Round($b.Width); $bh = [int][Math]::Round($b.Height)
      }
      if ($finite -and ($bw -gt 0 -or $bh -gt 0)) {
        $row = [ordered]@{}
        $row.index = $script:rows.Count
        $row.depth = $depth
        $row.type = $ctName
        $row.name = $nm
        $row.automation_id = $aid
        $row.path = $p
        $row.screen_rect = [ordered]@{ x = $bx; y = $by; w = $bw; h = $bh }
        [void]$script:rows.Add($row)
      } else {
        $script:skipped = $script:skipped + 1
      }
      Dump-Children $child ($depth + 1) $p
      $next = $null
      try { $next = $walker.GetNextSibling($child) } catch { $next = $null }
      $child = $next
    }
  }

  Dump-Children $win 1 ''
  $meta.controls_count = $script:rows.Count
  $meta.controls_skipped_empty = $script:skipped
  Write-Output ("UIACONTROLS " + $script:rows.Count + " skipped_empty=" + $script:skipped)

  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText((Join-Path $WorkDir 'tree.json'), ($script:rows | ConvertTo-Json -Depth 6), $enc)
  Write-Output "TREE saved"
}
catch {
  if (-not $meta.Contains('error')) { $meta.error = [string]$_.Exception.Message }
  Write-Output ("ERROR " + $meta.error)
}
finally {
  if ($proc -ne $null) {
    try { [void]$proc.CloseMainWindow() } catch {}
    Start-Sleep -Milliseconds 1000
    try {
      if (-not $proc.HasExited) { $proc.Kill(); $meta.killed = $true }
    } catch {}
    try { [void]$proc.WaitForExit(3000) } catch {}
    try { $meta.exited = [bool]$proc.HasExited } catch { $meta.exited = $false }
  }
  try {
    $enc2 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $WorkDir 'meta.json'), ($meta | ConvertTo-Json -Depth 8), $enc2)
  } catch {}
  Write-Output "CLOSED killed=$($meta.killed) exited=$($meta.exited)"
  if ($meta.Contains('error')) { exit 3 } else { exit 0 }
}
