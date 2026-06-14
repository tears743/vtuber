"""
Live2D 情绪 → 表情/动作 映射表

基于 mao_pro 模型的 model_dict.json emotionMap + expression 文件分析。
Director 脚本输出语义 emotion 标签，渲染层通过此表映射到实际文件 ID。

模型来源: D:\workspace\Open-LLM-VTuber\live2d-models\mao_pro
"""

# emotion → (expression_file, motion_file)
# expression: exp_01~08 对应 expressions/ 目录下的文件
# motion: mtn_01~04, special_01~03 对应 motions/ 目录下的文件

EMOTION_MAP = {
    # 情绪标签      表情ID      动作ID         说明
    "neutral":   ("exp_01", "mtn_02"),    # 默认正常，说话动作A
    "joy":       ("exp_02", "mtn_02"),    # 微笑，普通说话
    "excited":   ("exp_04", "special_01"),# 星星眼，魔法特效动作
    "surprise":  ("exp_07", "special_02"),# 惊讶大眼，大幅度反应
    "anger":     ("exp_08", "mtn_04"),    # 怒嘴怒线，激动说话
    "disgust":   ("exp_08", "mtn_04"),    # 同 anger 表情，激动
    "sadness":   ("exp_05", "mtn_03"),    # 委屈下嘴，强调动作
    "fear":      ("exp_05", "mtn_03"),    # 同 sadness
    "shy":       ("exp_06", "mtn_03"),    # 脸红+眉下压，强调
    "smirk":     ("exp_04", "special_01"),# 得意星星眼，魔法特效
    "amused":    ("exp_02", "mtn_02"),    # 被逗笑，同 joy
}

# model3.json 中的 LipSync 参数 — 音频驱动用
LIP_SYNC_PARAM = "ParamA"

# Idle 动作组
IDLE_MOTION = "mtn_01"

# 模型基础路径 (相对于 Open-LLM-VTuber 项目)
MODEL_PATH = "live2d-models/mao_pro/runtime/mao_pro.model3.json"


def get_expression_motion(emotion: str) -> tuple[str, str]:
    """
    根据 emotion 标签返回 (expression_id, motion_id)
    
    Args:
        emotion: Director 脚本中的 emotion 值
        
    Returns:
        (expression_id, motion_id) 元组
    """
    return EMOTION_MAP.get(emotion.lower(), EMOTION_MAP["neutral"])
