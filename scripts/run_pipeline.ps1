# ============================================================
# VideoFactory Pipeline (PowerShell)
#
# Flow: Collect -> Director -> TTS -> Align -> Overlay -> Visual -> Live2D -> Compose
#
# Usage:
#   .\scripts\run_pipeline.ps1                        # today
#   .\scripts\run_pipeline.ps1 -Date 2026-06-12      # specific date
#   .\scripts\run_pipeline.ps1 -Date 2026-06-12 -From tts         # start from step
#   .\scripts\run_pipeline.ps1 -Date 2026-06-12 -SkipDirector     # skip director
# ============================================================
param(
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [string]$From = "collect",
    [switch]$SkipDirector
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " VideoFactory Pipeline" -ForegroundColor Cyan
Write-Host " Date: $Date" -ForegroundColor Cyan
Write-Host " From: $From" -ForegroundColor Cyan
Write-Host " Skip Director: $SkipDirector" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$steps = @("collect", "download", "recognize", "director", "tts", "align", "overlay", "visual", "live2d", "compose")
$startIdx = [Array]::IndexOf($steps, $From)
if ($startIdx -lt 0) {
    Write-Host "[ERROR] Unknown step: $From" -ForegroundColor Red
    Write-Host "Available: $($steps -join ', ')"
    exit 1
}

# TTS check moved to inline (before tts step)


$total = $steps.Count - $startIdx
$current = 0

for ($i = $startIdx; $i -lt $steps.Count; $i++) {
    $step = $steps[$i]
    $current++

    if ($step -eq "director" -and $SkipDirector) {
        Write-Host "[$current/$total] Director - SKIPPED" -ForegroundColor DarkGray
        continue
    }

    $descTable = @{
        "collect"   = "Collect - data gathering"
        "download"  = "Download - media download"
        "recognize" = "Recognize - image/video recognition"
        "director"  = "Director - script generation"
        "tts"       = "TTS - voice synthesis"
        "align"     = "Align - timeline alignment"
        "overlay"   = "Overlay - transparent cards"
        "visual"    = "Visual - background layer"
        "live2d"    = "Live2D - character animation"
        "compose"   = "Compose - final mix"
    }
    $desc = $descTable[$step]

    Write-Host "[$current/$total] $desc ..." -ForegroundColor White
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    if ($step -eq "collect") {
        python -m agents.collector.run_teams --date $Date
    } elseif ($step -eq "download") {
        python -m agents.renderer.run_render --date $Date --step download
    } elseif ($step -eq "recognize") {
        python -m agents.renderer.run_render --date $Date --step recognize
    } elseif ($step -eq "director") {
        python -m agents.director.run_director --date $Date
    } elseif ($step -eq "tts") {
        # Check TTS service, auto-start if not running
        $ttsRunning = $false
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8808/health" -TimeoutSec 3 -ErrorAction Stop
            $ttsRunning = ($r.StatusCode -eq 200)
        } catch {
            $ttsRunning = $false
        }

        if (-not $ttsRunning) {
            Write-Host "  [TTS] Service not running, starting..." -ForegroundColor Yellow
            # Start TTS in a minimized window (WSL must stay alive for the server)
            Start-Process -WindowStyle Minimized -FilePath "wsl.exe" -ArgumentList "-d Ubuntu -- bash -lc `"cd ~ && export TORCH_MATMUL_PRECISION=high && python3 ~/tts_server.py --port 8808 --device cuda --reference-wav ~/baoer.mp3`""
            
            # Wait for TTS to be ready (max 90s, model loading takes ~25s)
            $waited = 0
            while ($waited -lt 90) {
                Start-Sleep -Seconds 3
                $waited += 3
                try {
                    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8808/health" -TimeoutSec 2 -ErrorAction Stop
                    if ($r.StatusCode -eq 200) {
                        $ttsRunning = $true
                        break
                    }
                } catch {}
                Write-Host "  [TTS] Waiting... ($waited`s)" -ForegroundColor DarkYellow
            }

            if (-not $ttsRunning) {
                Write-Host "  [ERROR] TTS service failed to start within 90s" -ForegroundColor Red
                exit 1
            }
        }
        Write-Host "  [TTS] Service ready." -ForegroundColor Green
        python -m agents.renderer.run_render --date $Date --step $step
    } elseif ($step -eq "overlay") {
        python -m agents.renderer.run_render --date $Date --step render
    } else {
        python -m agents.renderer.run_render --date $Date --step $step
    }

    $sw.Stop()
    $elapsed = $sw.Elapsed.ToString("mm\:ss")

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$current/$total] FAILED! ($elapsed)" -ForegroundColor Red
        exit 1
    }

    Write-Host "[$current/$total] Done. ($elapsed)" -ForegroundColor Green
    Write-Host ""
}

Write-Host "============================================================" -ForegroundColor Green
Write-Host " Pipeline Complete!" -ForegroundColor Green
Write-Host " Output: data\$Date\final\" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
