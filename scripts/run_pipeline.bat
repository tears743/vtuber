@echo off
REM ============================================================
REM VideoFactory 全流程管线
REM 
REM 流程: Director选题 -> TTS -> Align -> Overlay -> Visual -> Live2D -> Compose
REM 
REM 前置条件:
REM   1. TTS 服务已启动 (另一个终端跑 scripts\start_tts.bat)
REM   2. Python 环境就绪
REM
REM 用法: 
REM   scripts\run_pipeline.bat              -- 使用今天日期
REM   scripts\run_pipeline.bat 2026-06-12   -- 指定日期
REM   scripts\run_pipeline.bat 2026-06-12 --skip-director  -- 跳过选题(已有脚本)
REM   scripts\run_pipeline.bat 2026-06-12 --from tts       -- 从某步开始
REM ============================================================
setlocal enabledelayedexpansion

set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

set SKIP_DIRECTOR=0
set FROM_STEP=director

REM 解析参数
:parse_args
shift
if "%~1"=="" goto :done_args
if "%~1"=="--skip-director" (set SKIP_DIRECTOR=1 & goto :parse_args)
if "%~1"=="--from" (set FROM_STEP=%~2 & shift & goto :parse_args)
goto :parse_args
:done_args

echo ============================================================
echo  VideoFactory Pipeline
echo  Date: %DATE%
echo  From: %FROM_STEP%
echo  Skip Director: %SKIP_DIRECTOR%
echo ============================================================
echo.

REM 检查 TTS 服务
echo [CHECK] Verifying TTS service...
python -c "import requests;r=requests.get('http://127.0.0.1:8808/health',timeout=3);print('OK' if r.status_code==200 else 'FAIL')" 2>nul | findstr "OK" >nul
if errorlevel 1 (
    echo [ERROR] TTS service not running! Please start it first:
    echo         scripts\start_tts.bat
    echo.
    echo   Or start in a separate terminal and re-run this script.
    exit /b 1
)
echo [CHECK] TTS service OK.
echo.

REM ─── Step 计数 ───
set STEP_NUM=0
set STEPS=director tts align overlay visual live2d compose
set REACHED=0

REM ─── Director 选题 + 脚本生成 ───
if "%FROM_STEP%"=="director" set REACHED=1
if %REACHED%==1 if %SKIP_DIRECTOR%==0 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] Director - 选题 + 聚合脚本生成...
    python -m agents.director.run_director --date %DATE%
    if errorlevel 1 (
        echo [ERROR] Director failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] Director done.
    echo.
)

REM ─── TTS 语音合成 ───
if "%FROM_STEP%"=="tts" set REACHED=1
if %REACHED%==1 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] TTS - 语音合成...
    python -m agents.renderer.run_render --date %DATE% --step tts
    if errorlevel 1 (
        echo [ERROR] TTS failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] TTS done.
    echo.
)

REM ─── Align 时间轴对齐 ───
if "%FROM_STEP%"=="align" set REACHED=1
if %REACHED%==1 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] Align - 时间轴对齐...
    python -m agents.renderer.run_render --date %DATE% --step align
    if errorlevel 1 (
        echo [ERROR] Align failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] Align done.
    echo.
)

REM ─── Overlay 渲染 ───
if "%FROM_STEP%"=="overlay" set REACHED=1
if %REACHED%==1 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] Overlay - 透明弹幕/卡片渲染...
    python -m agents.renderer.run_render --date %DATE% --step render
    if errorlevel 1 (
        echo [ERROR] Overlay render failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] Overlay done.
    echo.
)

REM ─── Visual 渲染 ───
if "%FROM_STEP%"=="visual" set REACHED=1
if %REACHED%==1 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] Visual - 背景层渲染...
    python -m agents.renderer.run_render --date %DATE% --step visual
    if errorlevel 1 (
        echo [ERROR] Visual render failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] Visual done.
    echo.
)

REM ─── Live2D 渲染 ───
if "%FROM_STEP%"=="live2d" set REACHED=1
if %REACHED%==1 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] Live2D - 角色动画渲染...
    python -m agents.renderer.run_render --date %DATE% --step live2d
    if errorlevel 1 (
        echo [ERROR] Live2D render failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] Live2D done.
    echo.
)

REM ─── Compose 最终合成 ───
if "%FROM_STEP%"=="compose" set REACHED=1
if %REACHED%==1 (
    set /a STEP_NUM+=1
    echo [!STEP_NUM!/7] Compose - 最终合成...
    python -m agents.renderer.run_render --date %DATE% --step compose
    if errorlevel 1 (
        echo [ERROR] Compose failed!
        exit /b 1
    )
    echo [!STEP_NUM!/7] Compose done.
    echo.
)

echo ============================================================
echo  Pipeline Complete!
echo  Output: data\%DATE%\final\
echo ============================================================
