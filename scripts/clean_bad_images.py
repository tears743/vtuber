"""清理 manifest 中的 SVG/GIF 坏文件"""
import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

manifest_path = Path(r'D:\workspace\videoFactory\data\2026-07-05\media\manifest.json')
m = json.load(open(manifest_path, 'r', encoding='utf-8'))

bad_extensions = {'.gif', '.svg'}
removed = []

for key, entry in m.items():
    readme = entry.get("readme")
    if not readme:
        continue
    
    # 清理 readme.images
    images = readme.get("images", [])
    clean_images = []
    for img_path in images:
        p = Path(img_path)
        # 检查后缀
        if p.suffix.lower() in bad_extensions:
            removed.append(f"[ext] {img_path}")
            continue
        # 检查文件头
        if p.exists():
            with open(p, "rb") as f:
                header = f.read(256)
            if b"<svg" in header or (b"<?xml" in header):
                removed.append(f"[svg] {img_path}")
                p.unlink(missing_ok=True)
                continue
            if header[:3] == b"GIF":
                removed.append(f"[gif] {img_path}")
                p.unlink(missing_ok=True)
                continue
        clean_images.append(img_path)
    readme["images"] = clean_images
    
    # 清理 readme.recognized_images
    rec_imgs = readme.get("recognized_images", [])
    clean_rec = []
    for img in rec_imgs:
        img_path = img.get("path", "") if isinstance(img, dict) else img
        p = Path(img_path)
        if p.suffix.lower() in bad_extensions:
            removed.append(f"[ext/rec] {img_path}")
            continue
        if p.exists():
            with open(p, "rb") as f:
                header = f.read(256)
            if b"<svg" in header or b"<?xml" in header:
                removed.append(f"[svg/rec] {img_path}")
                p.unlink(missing_ok=True)
                continue
            if header[:3] == b"GIF":
                removed.append(f"[gif/rec] {img_path}")
                p.unlink(missing_ok=True)
                continue
        clean_rec.append(img)
    readme["recognized_images"] = clean_rec

# 保存
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(m, f, ensure_ascii=False, indent=2)

print(f"Removed {len(removed)} bad entries:")
for r in removed:
    print(f"  {r}")
