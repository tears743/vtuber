#!/bin/bash
# 测试 faster-whisper CUDA + 转录抖音视频

echo "=== Checking CUDA ==="
python3 -c "import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"

echo "=== Transcribing video ==="
python3 -c "
from faster_whisper import WhisperModel
import time

video_path = '/mnt/d/workspace/videoFactory/data/2026-06-12/media/test_douyin/video.mp4'

print('Loading model...')
t0 = time.time()
model = WhisperModel('large-v3', device='cuda', compute_type='float16')
print(f'Model loaded in {time.time()-t0:.1f}s')

print('Transcribing...')
t0 = time.time()
segments, info = model.transcribe(
    video_path,
    beam_size=5,
    language='zh',
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
)

text_parts = []
for seg in segments:
    text_parts.append(seg.text.strip())
    if len(text_parts) <= 5:
        print(f'  [{seg.start:.1f}-{seg.end:.1f}] {seg.text.strip()}')

elapsed = time.time() - t0
full_text = ''.join(text_parts)
print(f'\nDone in {elapsed:.1f}s')
print(f'Duration: {info.duration:.1f}s')
print(f'Segments: {len(text_parts)}')
print(f'Full text ({len(full_text)} chars):')
print(full_text[:500])
"
