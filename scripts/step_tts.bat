@echo off
REM ============================================================
REM Phase 1: TTS 语音合成
REM 前置: TTS 服务必须已启动 (scripts\start_tts.bat)
REM 用法: scripts\step_tts.bat [日期]
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

echo [STEP] TTS - Date: %DATE%
python -m agents.renderer.run_render --date %DATE% --step tts
if errorlevel 1 (
    echo [ERROR] TTS failed!
    exit /b 1
)
echo [STEP] TTS done.
