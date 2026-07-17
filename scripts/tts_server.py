"""VoxCPM2 HTTP server with cached ultimate-cloning context."""

import argparse
import io
import os
import sys
from typing import Optional

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.responses import Response


DEFAULT_REFERENCE_TEXT = (
    '哦，听说你想学功夫啊？来来来，我教你个绝招。这招叫做"宝儿飞天转"，'
    "是我自己改良的，练了好久才整明白。上次有个人跟我比划，我用这招直接把他"
    "打懵圈了，你要不要学嘛？"
)

app = FastAPI()
model = None
prompt_cache = None


class TTSRequest(BaseModel):
    text: str
    reference_wav_path: Optional[str] = None
    control_instruction: Optional[str] = None
    cfg_value: float = 3.0
    inference_timesteps: int = 32


@app.post("/generate")
async def generate(req: TTSRequest):
    global model, prompt_cache

    text = req.text
    if req.control_instruction:
        text = f"({req.control_instruction}){text}"

    print(
        f"[TTS] Generating: text='{text[:60]}', "
        f"timesteps={req.inference_timesteps}, cfg={req.cfg_value}",
        flush=True,
    )

    try:
        if prompt_cache is not None:
            from voxcpm.model.utils import next_and_close

            generate_result = model.tts_model._generate_with_prompt_cache(
                target_text=text,
                prompt_cache=prompt_cache,
                min_len=2,
                max_len=2048,
                inference_timesteps=req.inference_timesteps,
                cfg_value=req.cfg_value,
                retry_badcase=False,
                retry_badcase_max_times=1,
                retry_badcase_ratio_threshold=8.0,
                streaming=False,
            )
            wav_tensor, _, _ = next_and_close(generate_result)
            decode_audio = wav_tensor.squeeze(0).cpu().numpy()
            print(
                f"[TTS] Generated audio: shape={decode_audio.shape}, "
                f"max={np.abs(decode_audio).max():.4f}",
                flush=True,
            )
        else:
            decode_audio = model.generate(
                text=text,
                cfg_value=req.cfg_value,
                inference_timesteps=req.inference_timesteps,
            )
            print(f"[TTS] Generated audio (zero-shot): shape={decode_audio.shape}", flush=True)

        if decode_audio is None or len(decode_audio) == 0 or np.abs(decode_audio).max() < 1e-6:
            print("[TTS] WARNING: Audio is empty or silent!", flush=True, file=sys.stderr)

        buf = io.BytesIO()
        sf.write(buf, decode_audio, model.tts_model.sample_rate, format="WAV")
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")
    except Exception as exc:
        print(f"[TTS] ERROR: {exc}", flush=True, file=sys.stderr)
        import traceback

        traceback.print_exc()
        buf = io.BytesIO()
        sf.write(buf, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": "VoxCPM2",
        "prompt_cached": prompt_cache is not None,
        "clone_mode": prompt_cache.get("mode") if prompt_cache else "zero_shot",
    }


def main():
    global model, prompt_cache

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8808)
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--model-id", type=str, default="openbmb/VoxCPM2")
    parser.add_argument(
        "--reference-wav",
        type=str,
        default="/home/tears/baoer.mp3",
        help="Reference audio used for both isolated reference and continuation prompt.",
    )
    parser.add_argument(
        "--reference-text",
        type=str,
        default=DEFAULT_REFERENCE_TEXT,
        help="Exact transcript of --reference-wav for ultimate cloning.",
    )
    args = parser.parse_args()

    from voxcpm import VoxCPM

    print(f"Loading VoxCPM2 model from {args.model_id}...", flush=True)
    model = VoxCPM.from_pretrained(
        args.model_id,
        device=args.device,
        load_denoiser=False,
        optimize=True,
    )

    if args.reference_wav and os.path.exists(args.reference_wav):
        print(f"Pre-caching ultimate clone reference: {args.reference_wav}...", flush=True)
        prompt_cache = model.tts_model.build_prompt_cache(
            prompt_text=args.reference_text,
            prompt_wav_path=args.reference_wav,
            reference_wav_path=args.reference_wav,
        )
        print(f"Reference voice cached! Mode: {prompt_cache.get('mode')}", flush=True)

        print("Warming up with test sentence...", flush=True)
        from voxcpm.model.utils import next_and_close

        test_result = model.tts_model._generate_with_prompt_cache(
            target_text="你好，这是一个测试。",
            prompt_cache=prompt_cache,
            min_len=2,
            max_len=200,
            inference_timesteps=32,
            cfg_value=3.0,
            streaming=False,
        )
        test_wav, _, _ = next_and_close(test_result)
        print(
            f"Warmup done! Test audio shape: {test_wav.shape}, "
            f"max: {test_wav.abs().max():.4f}",
            flush=True,
        )
    else:
        print("No reference voice, running in zero-shot mode.", flush=True)

    print(f"Starting server on port {args.port}...", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
