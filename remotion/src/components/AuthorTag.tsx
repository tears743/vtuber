import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface AuthorTagProps {
  text?: string;
  position?: "bottom-left" | "bottom-right" | "top-left" | "top-right";
}

export const AuthorTag: React.FC<AuthorTagProps> = ({
  text = "",
  position = "bottom-left",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // 入场动画：滑入 + 淡入
  const enter = spring({
    fps,
    frame,
    config: { stiffness: 80, damping: 18 },
  });

  // 出场淡出
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const opacity = interpolate(enter, [0, 1], [0, 1]) * fadeOut;
  const slideX = interpolate(enter, [0, 1], [-30, 0]);

  // 位置计算
  const posStyle: React.CSSProperties = {};
  if (position.includes("bottom")) {
    posStyle.bottom = 80;
  } else {
    posStyle.top = 100;
  }
  if (position.includes("left")) {
    posStyle.left = 30;
  } else {
    posStyle.right = 30;
  }

  if (!text) return null;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          ...posStyle,
          opacity,
          transform: `translateX(${slideX}px)`,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 20px",
          borderRadius: 8,
          background: "rgba(0, 0, 0, 0.55)",
          backdropFilter: "blur(8px)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
          boxShadow: "0 4px 16px rgba(0, 0, 0, 0.3)",
        }}
      >
        <span
          style={{
            fontSize: 32,
            fontWeight: 600,
            color: "rgba(255, 255, 255, 0.95)",
            fontFamily: "'Microsoft YaHei', 'PingFang SC', sans-serif",
            letterSpacing: 1,
            textShadow: "0 1px 4px rgba(0, 0, 0, 0.4)",
          }}
        >
          {text}
        </span>
      </div>
    </AbsoluteFill>
  );
};
