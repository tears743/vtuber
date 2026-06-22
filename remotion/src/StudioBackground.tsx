import {
  AbsoluteFill,
  Img,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  staticFile,
} from "remotion";

/**
 * StudioBackground — 演播室背景动画
 * 
 * 在静态背景图上对特定区域叠加动效：
 * 1. 左上魔法阵 — 缓慢旋转
 * 2. 中上符文标记 — 脉冲发光
 * 3. 右上蓝色漩涡 — 旋转（反向）
 * 4. 左侧全息面板 — 数据扫描线
 * 5. 右侧全息面板 — 数据扫描线
 * 
 * 输出: 1080x1920, 30fps, 10s loop
 */

interface StudioBgProps {
  bgImage?: string;
}

// 图层在视频坐标系中的位置 (1080x1920)
const LAYERS = {
  magic_circle_left: { x: 50, y: 130, w: 150, h: 150, effect: "rotate" },
  rune_center: { x: 420, y: 100, w: 120, h: 120, effect: "pulse" },
  vortex_right: { x: 780, y: 60, w: 270, h: 220, effect: "rotate_reverse" },
  panel_left: { x: 0, y: 280, w: 230, h: 400, effect: "scan" },
  panel_right: { x: 750, y: 380, w: 330, h: 400, effect: "scan" },
};

const RotatingLayer: React.FC<{
  src: string;
  x: number;
  y: number;
  w: number;
  h: number;
  reverse?: boolean;
}> = ({ src, x, y, w, h, reverse = false }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  
  // 10秒一圈
  const angle = (reverse ? -1 : 1) * (t / 10) * 360;

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          transform: `rotate(${angle}deg)`,
          filter: "drop-shadow(0 0 8px rgba(100,180,255,0.4))",
        }}
      />
    </div>
  );
};

const PulsingLayer: React.FC<{
  src: string;
  x: number;
  y: number;
  w: number;
  h: number;
}> = ({ src, x, y, w, h }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // 2秒一个脉冲周期
  const pulse = 0.7 + 0.3 * Math.sin(t * Math.PI);
  const glow = 4 + 6 * Math.sin(t * Math.PI);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          opacity: pulse,
          filter: `drop-shadow(0 0 ${glow}px rgba(200,160,255,0.8)) brightness(${0.9 + 0.2 * Math.sin(t * Math.PI)})`,
        }}
      />
    </div>
  );
};

const ScanLayer: React.FC<{
  src: string;
  x: number;
  y: number;
  w: number;
  h: number;
}> = ({ src, x, y, w, h }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // 扫描线从上到下，3秒一个周期
  const scanY = ((t % 3) / 3) * h;
  // 轻微闪烁
  const flicker = 0.85 + 0.15 * Math.sin(t * 8);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        overflow: "hidden",
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "fill",
          opacity: flicker,
          filter: "brightness(1.1) saturate(1.2)",
        }}
      />
      {/* 扫描线 */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: scanY,
          width: "100%",
          height: 3,
          background: "linear-gradient(90deg, transparent, rgba(100,200,255,0.6), transparent)",
          boxShadow: "0 0 12px rgba(100,200,255,0.4)",
        }}
      />
      {/* 上方渐变遮罩 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 30,
          background: "linear-gradient(to bottom, rgba(0,0,0,0.3), transparent)",
        }}
      />
    </div>
  );
};

export const StudioBackground: React.FC<StudioBgProps> = ({
  bgImage = "studio/bg_starry.png",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // 星空整体微微呼吸
  const starBrightness = 1.0 + 0.03 * Math.sin(t * 0.5);

  return (
    <AbsoluteFill>
      {/* 底层背景 */}
      <Img
        src={staticFile(bgImage)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: `brightness(${starBrightness})`,
        }}
      />

      {/* 左上魔法阵 - 旋转 */}
      <RotatingLayer
        src="studio/layers/magic_circle_left.png"
        x={LAYERS.magic_circle_left.x}
        y={LAYERS.magic_circle_left.y}
        w={LAYERS.magic_circle_left.w}
        h={LAYERS.magic_circle_left.h}
      />

      {/* 中上符文 - 脉冲 */}
      <PulsingLayer
        src="studio/layers/rune_center.png"
        x={LAYERS.rune_center.x}
        y={LAYERS.rune_center.y}
        w={LAYERS.rune_center.w}
        h={LAYERS.rune_center.h}
      />

      {/* 右上漩涡 - 反向旋转 */}
      <RotatingLayer
        src="studio/layers/vortex_right.png"
        x={LAYERS.vortex_right.x}
        y={LAYERS.vortex_right.y}
        w={LAYERS.vortex_right.w}
        h={LAYERS.vortex_right.h}
        reverse
      />

      {/* 左侧面板 - 扫描 */}
      <ScanLayer
        src="studio/layers/panel_left.png"
        x={LAYERS.panel_left.x}
        y={LAYERS.panel_left.y}
        w={LAYERS.panel_left.w}
        h={LAYERS.panel_left.h}
      />

      {/* 右侧面板 - 扫描 */}
      <ScanLayer
        src="studio/layers/panel_right.png"
        x={LAYERS.panel_right.x}
        y={LAYERS.panel_right.y}
        w={LAYERS.panel_right.w}
        h={LAYERS.panel_right.h}
      />
    </AbsoluteFill>
  );
};
