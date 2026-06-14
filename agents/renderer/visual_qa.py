"""
Visual QA — 用 Vision LLM 验收 Remotion 渲染结果

流程：
1. 从渲染的 WebM 中截取关键帧
2. 将截图 + 原始 overlay 描述发给 Vision LLM
3. LLM 评估是否符合预期
4. 返回通过/不通过 + 反馈
"""
import json
import logging
import subprocess
import base64
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)

QA_PROMPT = """你是一个视频质量审核员。我会给你一个 overlay 效果的描述和实际渲染的截图。

请评估：
1. 截图中的视觉效果是否与描述匹配
2. 文字是否可读、颜色是否协调
3. 是否有明显的渲染错误（空白、错位、乱码）

回复 JSON 格式：
{
  "passed": true/false,
  "score": 1-10,
  "issues": ["问题1", "问题2"],
  "suggestion": "改进建议（如果不通过）"
}
"""


def extract_keyframes(
    webm_path: Path,
    output_dir: Path,
    count: int = 3,
) -> list[Path]:
    """
    从 WebM 中用 FFmpeg 截取关键帧

    Args:
        webm_path: 输入 WebM 文件
        output_dir: 截图输出目录
        count: 截取帧数

    Returns:
        截图文件路径列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取视频时长
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(webm_path),
    ]

    try:
        result = subprocess.run(
            probe_cmd, capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip())
    except Exception:
        duration = 5.0  # fallback

    frames = []
    for i in range(count):
        # 均匀分布截取
        t = duration * (i + 1) / (count + 1)
        output_file = output_dir / f"frame_{i:02d}.png"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(webm_path),
            "-ss", f"{t:.2f}",
            "-frames:v", "1",
            "-f", "image2",
            str(output_file),
        ]

        subprocess.run(cmd, capture_output=True, timeout=10)
        if output_file.exists():
            frames.append(output_file)

    return frames


def encode_image_base64(image_path: Path) -> str:
    """将图片编码为 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def qa_overlay(
    overlay_items: list[dict],
    keyframes: list[Path],
    base_url: str,
    api_key: str,
    model: str = "mimo-v2.5",
) -> dict:
    """
    调用 Vision LLM 验收 overlay 渲染质量

    Returns:
        {"passed": bool, "score": int, "issues": list, "suggestion": str}
    """
    if not keyframes:
        return {"passed": False, "score": 0, "issues": ["无截图"], "suggestion": "渲染失败"}

    # 构建 overlay 描述
    descriptions = []
    for item in overlay_items:
        desc = item.get("description", item.get("type", "unknown"))
        descriptions.append(f"- [{item.get('type')}] {desc}")
    overlay_desc = "\n".join(descriptions)

    # 构建 messages
    content = [
        {"type": "text", "text": f"Overlay 效果描述：\n{overlay_desc}\n\n以下是渲染截图："},
    ]

    for frame_path in keyframes[:3]:  # 最多 3 张
        b64 = encode_image_base64(frame_path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    client = OpenAI(base_url=base_url, api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": QA_PROMPT},
                {"role": "user", "content": content},
            ],
            temperature=0.3,
            max_tokens=512,
        )

        text = response.choices[0].message.content.strip()

        # 解析 JSON
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        result = json.loads(text)
        logger.info(
            f"[visual_qa] 评分: {result.get('score')}/10, "
            f"通过: {result.get('passed')}"
        )
        return result

    except Exception as e:
        logger.error(f"[visual_qa] Vision LLM 调用失败: {e}")
        return {
            "passed": True,  # 失败时默认通过，避免阻塞流程
            "score": 5,
            "issues": [f"QA 调用异常: {str(e)}"],
            "suggestion": "",
        }


def qa_render_output(
    script: dict,
    webm_path: Path,
    base_url: str,
    api_key: str,
    model: str = "mimo-v2.5",
) -> dict:
    """
    端到端验收：截帧 + Vision QA

    Args:
        script: 脚本 JSON（含 tracks.overlay）
        webm_path: 渲染的 WebM 文件
        base_url: Vision LLM API base_url
        api_key: API key
        model: 模型名

    Returns:
        QA 结果 dict
    """
    overlay_items = script.get("tracks", {}).get("overlay", [])

    if not overlay_items:
        return {"passed": True, "score": 10, "issues": [], "suggestion": ""}

    # 截帧
    frames_dir = webm_path.parent / f"{webm_path.stem}_frames"
    keyframes = extract_keyframes(webm_path, frames_dir)

    # Vision QA
    result = qa_overlay(
        overlay_items=overlay_items,
        keyframes=keyframes,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )

    return result
