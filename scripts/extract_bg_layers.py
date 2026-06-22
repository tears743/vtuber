"""
从背景图裁切动效元素为单独的 PNG（带透明通道）
原图: 1024x1024，最终视频: 1080x1920
compose 中 bg 会被 scale 到 1080x1920:force_original_aspect_ratio=increase, crop=1080:1920
即先按高度拉伸: 1024 → 1920 (ratio=1.875), 宽度变为 1024*1.875=1920 → crop到1080
实际使用区域: 原图中心 576px 宽度 (1080/1.875), 1024px 高度全用
offset_x = (1920-1080)/2 / 1.875 = 224px from left of original

所以原图坐标到视频坐标映射:
video_x = (orig_x - 224) * 1.875
video_y = orig_y * 1.875

先导出各区域的坐标（基于原图）
"""
from PIL import Image
import os

img = Image.open("assets/studio/bg_starry.png")
print(f"Image size: {img.size}")  # 1024x1024

# 基于视频截图估算原图中的区域坐标
# 视频 1080x1920, 截图中的位置（估算）→ 反推到 1024x1024
# 缩放比: 原图→视频: scale factor = 1920/1024 = 1.875
# crop 水平偏移: (1024*1.875 - 1080) / 2 = (1920-1080)/2 = 420 px in video space
# 所以视频x=0 对应原图x = 420/1.875 = 224

SCALE = 1.875
CROP_X = 224  # 原图中对应视频左边缘的x

def video_to_orig(vx, vy):
    """视频坐标 → 原图坐标"""
    ox = vx / SCALE + CROP_X
    oy = vy / SCALE
    return int(ox), int(oy)

def orig_to_video(ox, oy):
    """原图坐标 → 视频坐标"""
    vx = (ox - CROP_X) * SCALE
    vy = oy * SCALE
    return int(vx), int(vy)

# 从截图估算各区域在视频中的位置（基于 1080x1920 视频）
# 1. 左上魔法阵: 视频约 (50,130) - (200,280)
# 2. 中上符文标记: 视频约 (420,100) - (540,220)  
# 3. 右上蓝色漩涡: 视频约 (780,60) - (1000,250)
# 4. 左侧全息面板: 视频约 (0,280) - (210,650)
# 5. 右侧全息面板: 视频约 (750,380) - (1080,750)

regions = {
    "magic_circle_left": (50, 130, 200, 280),     # vx1, vy1, vx2, vy2
    "rune_center": (420, 100, 540, 220),
    "vortex_right": (780, 60, 1050, 280),
    "panel_left": (0, 280, 230, 680),
    "panel_right": (750, 380, 1080, 780),
}

os.makedirs("assets/studio/layers", exist_ok=True)

for name, (vx1, vy1, vx2, vy2) in regions.items():
    ox1, oy1 = video_to_orig(vx1, vy1)
    ox2, oy2 = video_to_orig(vx2, vy2)
    # Clamp to image bounds
    ox1 = max(0, min(1024, ox1))
    oy1 = max(0, min(1024, oy1))
    ox2 = max(0, min(1024, ox2))
    oy2 = max(0, min(1024, oy2))
    
    print(f"{name}: video({vx1},{vy1})-({vx2},{vy2}) -> orig({ox1},{oy1})-({ox2},{oy2})")
    
    # Crop the region
    crop = img.crop((ox1, oy1, ox2, oy2))
    crop.save(f"assets/studio/layers/{name}.png")
    print(f"  Saved: {crop.size}")

print("\nDone! Check assets/studio/layers/")
