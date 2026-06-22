import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import React, { useMemo } from "react";

/**
 * MeteorOverlay v10 — 基于 Aceternity UI Meteors 组件的实现
 * 核心原理：
 * - 每颗流星是一个小圆点（头部）
 * - 尾巴用 ::before 伪元素（这里用子 div 模拟）的 linear-gradient 实现
 * - 动画：rotate(215deg) + translateX(-500px)，从右上到左下
 * - 用 Remotion interpolate 替代 CSS keyframes
 */

function seededRandom(seed: number): number {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

interface MeteorData {
  id: number;
  left: number;         // 起始 left 位置 (px)
  top: number;          // 起始 top 位置 (px)  
  delay: number;        // 延迟（帧）
  duration: number;     // 一次动画持续帧数
  tailWidth: number;    // 尾巴长度
}

function generateMeteors(count: number, width: number, height: number): MeteorData[] {
  const meteors: MeteorData[] = [];
  for (let i = 0; i < count; i++) {
    const r = (s: number) => seededRandom(i * 29 + s);
    meteors.push({
      id: i,
      left: r(0) * width * 0.8 - width * 0.2, // 偏左侧起始
      top: r(1) * height * 0.5 - height * 0.3, // 上半部分
      delay: Math.floor(r(2) * 300),             // 0-300帧延迟
      duration: Math.floor(40 + r(3) * 60),      // 40-100帧 (1.3-3.3秒)
      tailWidth: 50 + r(4) * 100,                // 50-150px 尾巴
    });
  }
  return meteors;
}

const SingleMeteor: React.FC<{ data: MeteorData; frame: number }> = ({ data, frame }) => {
  const { left, top, delay, duration, tailWidth } = data;
  
  // 循环：300帧 = 10秒
  const loopFrame = ((frame - delay) % 300 + 300) % 300;
  
  // 只在 duration 帧内显示
  if (loopFrame >= duration) return null;
  
  const progress = loopFrame / duration;
  
  // 沿 X 轴正方向平移（rotate(35deg) 后变成向右下对角线运动）
  const translateX = interpolate(progress, [0, 1], [0, 800]);
  
  // 透明度：前70%可见，后30%淡出
  const opacity = interpolate(progress, [0, 0.05, 0.7, 1], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  
  return (
    <div
      style={{
        position: "absolute",
        top: top,
        left: left,
        // 关键：旋转35度（左上→右下），再沿局部X轴正方向平移
        transform: `rotate(35deg) translateX(${translateX}px)`,
        opacity,
      }}
    >
      {/* 流星头部：小圆点 */}
      <div
        style={{
          width: 2,
          height: 2,
          borderRadius: "50%",
          backgroundColor: "#fff",
          boxShadow: [
            "0 0 2px 1px rgba(255,255,255,0.8)",
            "0 0 6px 2px rgba(0,200,255,0.6)",
            "0 0 12px 4px rgba(0,150,255,0.3)",
          ].join(", "),
        }}
      />
      {/* 流星尾巴：渐变条（尾巴在左侧，头部在右侧） */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          transform: "translateY(-50%)",
          right: 2, // 尾巴在头部左侧
          width: tailWidth,
          height: 1,
          background: "linear-gradient(to left, transparent, rgba(100,200,255,0.4), rgba(180,240,255,0.8))",
          borderRadius: "0.5px",
        }}
      />
    </div>
  );
};

const Star: React.FC<{ x: number; y: number; size: number; phase: number; frame: number }> = ({
  x, y, size, phase, frame,
}) => {
  const time = frame / 30;
  const twinkle = Math.pow((Math.sin(time * 0.7 + phase) + 1) / 2, 3);
  const alpha = twinkle * 0.5 + 0.05;
  if (alpha < 0.1) return null;
  
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: size,
        height: size,
        borderRadius: "50%",
        backgroundColor: `rgba(200, 240, 255, ${alpha})`,
        boxShadow: `0 0 ${size * 2}px ${size * 0.5}px rgba(150, 220, 255, ${alpha * 0.3})`,
      }}
    />
  );
};

export const MeteorOverlay: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  
  const meteors = useMemo(() => generateMeteors(30, width, height), [width, height]);
  
  const stars = useMemo(() => {
    const result: { x: number; y: number; size: number; phase: number }[] = [];
    for (let i = 0; i < 40; i++) {
      const r = (s: number) => seededRandom(i * 67 + s + 500);
      result.push({
        x: r(0) * width,
        y: r(1) * height,
        size: 0.8 + r(2) * 1.2,
        phase: r(3) * Math.PI * 2,
      });
    }
    return result;
  }, [width, height]);

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent", overflow: "hidden" }}>
      {stars.map((s, i) => (
        <Star key={`s-${i}`} x={s.x} y={s.y} size={s.size} phase={s.phase} frame={frame} />
      ))}
      {meteors.map((m) => (
        <SingleMeteor key={`m-${m.id}`} data={m} frame={frame} />
      ))}
    </AbsoluteFill>
  );
};
