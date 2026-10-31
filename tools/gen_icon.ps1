# 生成应用图标位图（GDI+）：RoundedRect + 渐变 + 均衡器竖条
# 输出 build\icon\i<size>.png，再由 tools\gen_icon.py 组装成 .ico
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $root "build\icon"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function New-RoundedPath([single]$x, [single]$y, [single]$w, [single]$h, [single]$r) {
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $d = $r * 2
  $p.AddArc($x, $y, $d, $d, 180, 90)
  $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
  $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
  $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

function New-IconBitmap([int]$S) {
  $bmp = New-Object System.Drawing.Bitmap($S, $S, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.Clear([System.Drawing.Color]::Transparent)

  $k = $S / 512.0
  $bg = New-RoundedPath (0) (0) $S $S (118 * $k)
  $rect = New-Object System.Drawing.RectangleF(0, 0, $S, $S)
  $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    $rect,
    [System.Drawing.Color]::FromArgb(255, 124, 92, 255),
    [System.Drawing.Color]::FromArgb(255, 255, 77, 109),
    [System.Drawing.Drawing2D.LinearGradientMode]::ForwardDiagonal)
  # 中间加一个紫色节点，模拟三色渐变
  $blend = New-Object System.Drawing.Drawing2D.ColorBlend
  $blend.Colors = @(
    [System.Drawing.Color]::FromArgb(255, 124, 92, 255),
    [System.Drawing.Color]::FromArgb(255, 192, 69, 255),
    [System.Drawing.Color]::FromArgb(255, 255, 77, 109))
  $blend.Positions = @(0.0, 0.52, 1.0)
  $brush.InterpolationColors = $blend
  $g.FillPath($brush, $bg)

  # 顶部高光
  $sheenPath = New-RoundedPath (0) (0) $S (300 * $k) (118 * $k)
  $sr = New-Object System.Drawing.RectangleF(0, 0, $S, (300 * $k))
  $sbrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    $sr,
    [System.Drawing.Color]::FromArgb(88, 255, 255, 255),
    [System.Drawing.Color]::FromArgb(0, 255, 255, 255),
    [System.Drawing.Drawing2D.LinearGradientMode]::Vertical)
  $g.FillPath($sbrush, $sheenPath)

  # 均衡器竖条
  $bars = @(
    @(105, 196, 120, 222),
    @(189, 146, 220, 255),
    @(273, 176, 160, 222),
    @(357, 126, 260, 255))
  foreach ($b in $bars) {
    $x = [single]($b[0] * $k); $y = [single]($b[1] * $k)
    $h = [single]($b[2] * $k); $w = [single](58 * $k)
    $r = $w / 2
    $path = New-RoundedPath $x $y $w $h $r
    $br = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb([int]$b[3], 255, 255, 255))
    $g.FillPath($br, $path)
    $br.Dispose()
    $path.Dispose()
  }

  $g.Dispose()
  return $bmp
}

$master = New-IconBitmap 512
$sizes = @(256, 128, 64, 48, 32, 24, 16)
foreach ($s in $sizes) {
  $small = New-Object System.Drawing.Bitmap($s, $s, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $sg = [System.Drawing.Graphics]::FromImage($small)
  $sg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $sg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $sg.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
  $sg.Clear([System.Drawing.Color]::Transparent)
  $sg.DrawImage($master, (New-Object System.Drawing.Rectangle(0, 0, $s, $s)))
  $sg.Dispose()
  $p = Join-Path $outDir ("i{0}.png" -f $s)
  $small.Save($p, [System.Drawing.Imaging.ImageFormat]::Png)
  $small.Dispose()
  Write-Output ("[+] {0}px {1}" -f $s, (Get-Item $p).Length)
}
$master.Save((Join-Path $outDir "i512.png"), [System.Drawing.Imaging.ImageFormat]::Png)
$master.Dispose()
Write-Output ("[+] 512px {0}" -f (Get-Item (Join-Path $outDir "i512.png")).Length)
