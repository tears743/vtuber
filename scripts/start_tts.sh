#!/bin/bash
# VoxCPM TTS Server 启动脚本
# 在 WSL 中运行，CUDA 加速
# 从 Windows 侧调用: wsl bash /home/tears/start_tts.sh

set -e

echo "=========================================="
echo "  VoxCPM2 TTS Server (CUDA)"
echo "=========================================="

# 激活 venv
source /home/tears/voxcpm_env/bin/activate

# 参考音频（极致克隆用）
REF_WAV="/home/tears/baoer.mp3"
SERVER_SCRIPT="/mnt/d/workspace/videoFactory/scripts/tts_server.py"
if [ ! -f "$REF_WAV" ]; then
    echo "[WARN] Reference WAV not found: $REF_WAV"
    echo "[WARN] Running in zero-shot mode (no voice cloning)"
    REF_WAV=""
fi

PORT=${1:-8808}
DEVICE=${2:-cuda}

echo "Port: $PORT"
echo "Device: $DEVICE"
echo "Reference: $REF_WAV"
echo "=========================================="

if [ -n "$REF_WAV" ]; then
    python "$SERVER_SCRIPT" --port "$PORT" --device "$DEVICE" --reference-wav "$REF_WAV"
else
    python "$SERVER_SCRIPT" --port "$PORT" --device "$DEVICE" --reference-wav ""
fi
