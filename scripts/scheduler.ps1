# ============================================================
# VideoFactory Scheduler - 定时自动跑全流程
#
# Usage:
#   .\scripts\scheduler.ps1                          # 交互式设置定时规则
#   .\scripts\scheduler.ps1 -Cron "0 8 * * *"       # 每天 8:00 跑
#   .\scripts\scheduler.ps1 -Cron "0 8,20 * * *"    # 每天 8:00 和 20:00 跑
#   .\scripts\scheduler.ps1 -Interval 60            # 每 60 分钟跑一次
#   .\scripts\scheduler.ps1 -Once "08:00"           # 今天 08:00 跑一次
#
# Cron 格式: 分 时 日 月 周 (标准5字段)
# ============================================================
param(
    [string]$Cron = "",
    [int]$Interval = 0,
    [string]$Once = "",
    [string]$From = "collect",
    [string]$To = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pipelineScript = Join-Path $scriptRoot "run_pipeline.ps1"

# ============================================================
# Cron 解析器
# ============================================================
function Parse-CronField {
    param([string]$Field, [int]$Min, [int]$Max)
    
    $values = @()
    foreach ($part in $Field.Split(",")) {
        if ($part -eq "*") {
            $values += $Min..$Max
        } elseif ($part -match "^\*/(\d+)$") {
            $step = [int]$Matches[1]
            for ($i = $Min; $i -le $Max; $i += $step) { $values += $i }
        } elseif ($part -match "^(\d+)-(\d+)$") {
            $values += [int]$Matches[1]..[int]$Matches[2]
        } elseif ($part -match "^\d+$") {
            $values += [int]$part
        }
    }
    return $values | Sort-Object -Unique
}

function Test-CronMatch {
    param([string]$CronExpr, [DateTime]$Time)
    
    $fields = $CronExpr.Trim().Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($fields.Count -ne 5) { return $false }
    
    $minutes = Parse-CronField $fields[0] 0 59
    $hours   = Parse-CronField $fields[1] 0 23
    $days    = Parse-CronField $fields[2] 1 31
    $months  = Parse-CronField $fields[3] 1 12
    $weekdays = Parse-CronField $fields[4] 0 6
    
    $dow = [int]$Time.DayOfWeek  # Sunday=0
    
    return (
        ($minutes -contains $Time.Minute) -and
        ($hours -contains $Time.Hour) -and
        ($days -contains $Time.Day) -and
        ($months -contains $Time.Month) -and
        ($weekdays -contains $dow)
    )
}

function Get-NextCronTime {
    param([string]$CronExpr, [DateTime]$After)
    
    $check = $After.AddMinutes(1)
    $check = $check.AddSeconds(-$check.Second).AddMilliseconds(-$check.Millisecond)
    
    # 最多检查未来 7 天
    $limit = $After.AddDays(7)
    while ($check -lt $limit) {
        if (Test-CronMatch $CronExpr $check) {
            return $check
        }
        $check = $check.AddMinutes(1)
    }
    return $null
}

# ============================================================
# 执行 Pipeline
# ============================================================
function Run-Pipeline {
    param([string]$FromStep, [string]$ToStep)
    
    $today = Get-Date -Format "yyyy-MM-dd"
    $timestamp = Get-Date -Format "HH:mm:ss"
    
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host " [Scheduler] 触发 Pipeline @ $timestamp" -ForegroundColor Magenta
    $toInfo = if ($ToStep) { " | To: $ToStep" } else { "" }
    Write-Host " Date: $today | From: $FromStep$toInfo" -ForegroundColor Magenta
    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host ""
    
    if ($DryRun) {
        Write-Host " [DryRun] 跳过实际执行" -ForegroundColor Yellow
        return
    }
    
    # 记录日志
    $logDir = Join-Path (Split-Path $scriptRoot -Parent) "data\$today\logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $logFile = Join-Path $logDir "pipeline_$(Get-Date -Format 'HHmmss').log"
    
    try {
        $pipeArgs = @("-ExecutionPolicy", "Bypass", "-File", $pipelineScript, "-Date", $today, "-From", $FromStep)
        if ($ToStep) { $pipeArgs += @("-To", $ToStep) }
        powershell @pipeArgs 2>&1 | Tee-Object -FilePath $logFile
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host " [Scheduler] ✅ Pipeline 完成!" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host " [Scheduler] ❌ Pipeline 失败 (exit: $LASTEXITCODE)" -ForegroundColor Red
        }
    } catch {
        Write-Host " [Scheduler] 💥 异常: $_" -ForegroundColor Red
    }
    
    Write-Host " [Scheduler] 日志: $logFile" -ForegroundColor DarkGray
}

# ============================================================
# 交互式设置
# ============================================================
function Show-InteractiveMenu {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " VideoFactory Scheduler" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host " 选择定时规则:" -ForegroundColor White
    Write-Host ""
    Write-Host "  1. 每天定时跑 (输入时间，如 08:00)" -ForegroundColor White
    Write-Host "  2. 每天跑两次 (输入两个时间，如 08:00,20:00)" -ForegroundColor White
    Write-Host "  3. 每隔 N 分钟跑一次" -ForegroundColor White
    Write-Host "  4. 自定义 Cron 表达式" -ForegroundColor White
    Write-Host "  5. 指定时间跑一次" -ForegroundColor White
    Write-Host ""
    
    $choice = Read-Host "  请选择 (1-5)"
    
    switch ($choice) {
        "1" {
            $time = Read-Host "  输入时间 (格式 HH:mm，如 08:00)"
            $h, $m = $time.Split(":")
            return "$m $h * * *"
        }
        "2" {
            $times = Read-Host "  输入时间 (逗号分隔，如 08:00,20:00)"
            $parts = $times.Split(",")
            $hours = @()
            $minute = ""
            foreach ($t in $parts) {
                $h, $m = $t.Trim().Split(":")
                $hours += $h
                $minute = $m
            }
            return "$minute $($hours -join ',') * * *"
        }
        "3" {
            $mins = Read-Host "  输入间隔分钟数"
            $script:Interval = [int]$mins
            return ""
        }
        "4" {
            $expr = Read-Host "  输入 Cron 表达式 (分 时 日 月 周)"
            return $expr
        }
        "5" {
            $time = Read-Host "  输入时间 (格式 HH:mm)"
            $script:Once = $time
            return ""
        }
        default {
            Write-Host "  无效选择" -ForegroundColor Red
            exit 1
        }
    }
}

# ============================================================
# Main
# ============================================================

# 如果没有参数，进入交互模式
if (-not $Cron -and $Interval -eq 0 -and -not $Once) {
    $Cron = Show-InteractiveMenu
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " VideoFactory Scheduler - Running" -ForegroundColor Cyan
Write-Host " Pipeline From: $From" -ForegroundColor Cyan

# 模式1: 单次执行
if ($Once) {
    $targetTime = [DateTime]::ParseExact($Once, "HH:mm", $null)
    $now = Get-Date
    if ($targetTime -lt $now) {
        $targetTime = $targetTime.AddDays(1)
    }
    $wait = $targetTime - $now
    
    Write-Host " Mode: 单次执行 @ $Once" -ForegroundColor Cyan
    Write-Host " 等待: $([math]::Round($wait.TotalMinutes, 1)) 分钟" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host " 按 Ctrl+C 取消" -ForegroundColor DarkGray
    
    Start-Sleep -Seconds $wait.TotalSeconds
    Run-Pipeline -FromStep $From -ToStep $To
    exit 0
}

# 模式2: 固定间隔
if ($Interval -gt 0) {
    Write-Host " Mode: 每 $Interval 分钟" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host " 按 Ctrl+C 停止" -ForegroundColor DarkGray
    Write-Host ""
    
    # 立即跑第一次
    Run-Pipeline -FromStep $From -ToStep $To
    
    while ($true) {
        $next = (Get-Date).AddMinutes($Interval)
        Write-Host ""
        Write-Host " [Scheduler] 下次执行: $($next.ToString('HH:mm:ss')) (等待 $Interval 分钟)" -ForegroundColor DarkGray
        Start-Sleep -Seconds ($Interval * 60)
        Run-Pipeline -FromStep $From -ToStep $To
    }
}

# 模式3: Cron 表达式
if ($Cron) {
    $nextTime = Get-NextCronTime $Cron (Get-Date)
    Write-Host " Mode: Cron [$Cron]" -ForegroundColor Cyan
    if ($nextTime) {
        Write-Host " 下次执行: $($nextTime.ToString('yyyy-MM-dd HH:mm'))" -ForegroundColor Cyan
    }
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host " 按 Ctrl+C 停止" -ForegroundColor DarkGray
    Write-Host ""
    
    while ($true) {
        $now = Get-Date
        if (Test-CronMatch $Cron $now) {
            Run-Pipeline -FromStep $From -ToStep $To
            # 等待当前分钟过去，避免重复触发
            Start-Sleep -Seconds (60 - $now.Second)
        }
        
        # 每 30 秒检查一次
        Start-Sleep -Seconds 30
        
        # 每小时打印一次心跳
        if ((Get-Date).Second -lt 30 -and (Get-Date).Minute -eq 0) {
            $nextTime = Get-NextCronTime $Cron (Get-Date)
            if ($nextTime) {
                Write-Host " [Scheduler] 💓 运行中 | 下次: $($nextTime.ToString('MM-dd HH:mm'))" -ForegroundColor DarkGray
            }
        }
    }
}

Write-Host " [Scheduler] 未配置定时规则，退出" -ForegroundColor Yellow
