"""
Layout Validator - Remotion 元素碰撞检测与自动修正

在 Remotion 渲染前检查同一时间段内的 overlay 元素是否存在位置重叠，
如果有冲突则自动调整 offsetY 使元素不重叠。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 各组件的默认尺寸估算 (width, height) in px
# 基于 1080x1920 竖屏分辨率
COMPONENT_SIZES = {
    "comment_scroll": (900, 600),
    "data_reveal": (800, 400),
    "info_panel": (900, 500),
    "highlight_text": (900, 200),
    "quote_box": (800, 300),
    "code_scroll": (900, 500),
    "stats_card": (500, 350),
    "model_card": (800, 450),
    "ranking_table": (900, 600),
}

# 默认尺寸（未知组件）
DEFAULT_SIZE = (800, 400)

# 屏幕安全区域
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 1920
SAFE_MARGIN = 40


def _get_component_size(item: dict) -> tuple[int, int]:
    """获取组件的估算尺寸"""
    comp_type = item.get("type", "")
    base_w, base_h = COMPONENT_SIZES.get(comp_type, DEFAULT_SIZE)
    scale = item.get("scale", 1.0)
    return int(base_w * scale), int(base_h * scale)


def _get_position_anchor(item: dict) -> tuple[int, int]:
    """
    根据 position 字符串计算元素中心锚点坐标
    返回 (center_x, center_y) 基于屏幕坐标
    """
    position = item.get("position", "center")
    if not position:
        position = "center"
    
    # 水平
    if "left" in position:
        cx = SAFE_MARGIN + 400
    elif "right" in position:
        cx = SCREEN_WIDTH - SAFE_MARGIN - 400
    else:
        cx = SCREEN_WIDTH // 2
    
    # 垂直
    if "top" in position:
        cy = 80 + 250
    elif "bottom" in position:
        cy = SCREEN_HEIGHT - 80 - 250
    else:
        cy = SCREEN_HEIGHT // 2
    
    return cx, cy


def _get_bounding_box(item: dict) -> tuple[int, int, int, int]:
    """
    计算元素的边界框 (x1, y1, x2, y2)
    """
    w, h = _get_component_size(item)
    cx, cy = _get_position_anchor(item)
    
    # 应用 offset
    offset_x = item.get("offsetX", 0) or 0
    offset_y = item.get("offsetY", 0) or 0
    
    cx += offset_x
    cy += offset_y
    
    x1 = cx - w // 2
    y1 = cy - h // 2
    x2 = cx + w // 2
    y2 = cy + h // 2
    
    return x1, y1, x2, y2


def _time_overlaps(a: dict, b: dict) -> bool:
    """检查两个元素的时间区间是否有交集"""
    a_start = a.get("start_ms", 0)
    a_end = a_start + a.get("duration_ms", 5000)
    b_start = b.get("start_ms", 0)
    b_end = b_start + b.get("duration_ms", 5000)
    
    return a_start < b_end and b_start < a_end


def _boxes_overlap(box_a: tuple, box_b: tuple) -> bool:
    """检查两个边界框是否重叠"""
    a_x1, a_y1, a_x2, a_y2 = box_a
    b_x1, b_y1, b_x2, b_y2 = box_b
    
    # 不重叠的条件取反
    return not (a_x2 <= b_x1 or b_x2 <= a_x1 or a_y2 <= b_y1 or b_y2 <= a_y1)


class LayoutValidator:
    """检查 overlay 元素时间重叠 + 位置碰撞，自动修正"""
    
    def validate_and_fix(self, overlay_items: list[dict]) -> list[dict]:
        """
        检查并修正 overlay 元素布局。
        
        策略：
        1. 按时间分组：找出同一时间段内同时可见的元素
        2. 对同时可见的元素，检查边界框是否重叠
        3. 如果重叠，向下偏移冲突元素，循环检查直到无任何重叠
        
        Args:
            overlay_items: 原始 overlay 列表
            
        Returns:
            修正后的 overlay 列表（原列表不变，返回新列表）
        """
        if not overlay_items or len(overlay_items) <= 1:
            return overlay_items
        
        # 深拷贝，避免修改原数据
        import copy
        items = copy.deepcopy(overlay_items)
        
        total_fixes = 0
        gap = 30  # 元素间距
        max_attempts = 20  # 防止无限循环
        
        # 对每个元素，确保它和所有时间重叠的已定位元素都不碰撞
        for i in range(len(items)):
            attempts = 0
            while attempts < max_attempts:
                has_collision = False
                
                for j in range(i):
                    # 时间不重叠则跳过
                    if not _time_overlaps(items[i], items[j]):
                        continue
                    
                    # 检查空间重叠
                    box_i = _get_bounding_box(items[i])
                    box_j = _get_bounding_box(items[j])
                    
                    if _boxes_overlap(box_i, box_j):
                        # 将 items[i] 移动到 items[j] 正下方
                        _, _, _, j_bottom = box_j
                        _, i_top, _, _ = box_i
                        
                        needed_offset = j_bottom - i_top + gap
                        current_offset_y = items[i].get("offsetY", 0) or 0
                        items[i]["offsetY"] = current_offset_y + needed_offset
                        
                        has_collision = True
                        total_fixes += 1
                        logger.warning(
                            f"[layout] 碰撞修正: item[{i}] ({items[i].get('type')}) "
                            f"与 item[{j}] ({items[j].get('type')}) 重叠, "
                            f"offsetY += {needed_offset}px"
                        )
                        break  # 重新从头检查所有已定位元素
                
                if not has_collision:
                    break  # 当前元素与所有已定位元素都不冲突
                attempts += 1
        
        # 边界检查：确保所有元素完全在可视区域内
        for item in items:
            x1, y1, x2, y2 = _get_bounding_box(item)
            w, h = _get_component_size(item)
            current_offset_x = item.get("offsetX", 0) or 0
            current_offset_y = item.get("offsetY", 0) or 0
            fixed = False
            
            # 超出底部 → 向上拉
            if y2 > SCREEN_HEIGHT - SAFE_MARGIN:
                pull_up = y2 - (SCREEN_HEIGHT - SAFE_MARGIN)
                item["offsetY"] = current_offset_y - pull_up
                current_offset_y = item["offsetY"]
                fixed = True
            
            # 超出顶部 → 向下推
            x1, y1, x2, y2 = _get_bounding_box(item)
            if y1 < SAFE_MARGIN:
                push_down = SAFE_MARGIN - y1
                item["offsetY"] = current_offset_y + push_down
                current_offset_y = item["offsetY"]
                fixed = True
            
            # 超出右边 → 向左拉
            x1, y1, x2, y2 = _get_bounding_box(item)
            if x2 > SCREEN_WIDTH - SAFE_MARGIN:
                pull_left = x2 - (SCREEN_WIDTH - SAFE_MARGIN)
                item["offsetX"] = current_offset_x - pull_left
                current_offset_x = item["offsetX"]
                fixed = True
            
            # 超出左边 → 向右推
            x1, y1, x2, y2 = _get_bounding_box(item)
            if x1 < SAFE_MARGIN:
                push_right = SAFE_MARGIN - x1
                item["offsetX"] = current_offset_x + push_right
                fixed = True
            
            # 如果元素本身比屏幕大（拉不回来），缩小
            x1, y1, x2, y2 = _get_bounding_box(item)
            if (y2 - y1) > (SCREEN_HEIGHT - 2 * SAFE_MARGIN) or (x2 - x1) > (SCREEN_WIDTH - 2 * SAFE_MARGIN):
                available_h = SCREEN_HEIGHT - 2 * SAFE_MARGIN
                available_w = SCREEN_WIDTH - 2 * SAFE_MARGIN
                scale_h = available_h / h if h > 0 else 1.0
                scale_w = available_w / w if w > 0 else 1.0
                shrink = min(scale_h, scale_w, 1.0)
                shrink = max(shrink, 0.5)  # 最小缩到 50%
                current_scale = item.get("scale", 1.0) or 1.0
                item["scale"] = round(current_scale * shrink, 2)
                fixed = True
            
            if fixed:
                total_fixes += 1
                logger.warning(
                    f"[layout] 边界修正: {item.get('type')} "
                    f"offsetX={item.get('offsetX', 0)}, offsetY={item.get('offsetY', 0)}, "
                    f"scale={item.get('scale', 1.0)}"
                )
        
        if total_fixes:
            logger.info(f"[layout] 共修正 {total_fixes} 处碰撞/边界问题")
        else:
            logger.info(f"[layout] 布局检查通过，无碰撞")
        
        return items
