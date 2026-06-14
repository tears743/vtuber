import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface DataRevealProps {
  title?: string;
  value?: string;
  unit?: string;
  description?: string;
  color?: string;
  style?: StyleType;
  // Director 生成的格式
  number?: string;
  label?: string;
}

export const DataReveal: React.FC<DataRevealProps> = (props) => {
  const {
    unit = "",
    color,
    style = "default",
  } = props;
  // 兼容 Director 格式: {number, label} → {value, title}
  const title = props.title || props.label || "";
  const value = props.value || props.number || "0";
  const description = props.description || "";
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = getTokens(style);

  const accentColor = color || t.accentColor;

  // 数字弹入
  const valueSpring = spring({
    fps,
    frame,
    config: { stiffness: 60, damping: 13, mass: 1.1 },
  });
  const valueScale = interpolate(valueSpring, [0, 1], [0.7, 1]);
  const valueOpacity = interpolate(valueSpring, [0, 1], [0, 1]);

  // 标题淡入
  const titleOpacity = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const titleY = interpolate(frame, [0, 14], [8, 0], { extrapolateRight: "clamp" });

  // 描述
  const descOpacity = interpolate(frame, [20, 32], [0, 1], { extrapolateRight: "clamp" });

  // 退出
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        fontFamily: t.fontFamily,
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          background: t.cardBg,
          backdropFilter: `blur(${t.cardBlur}px)`,
          borderRadius: t.cardBorderRadius,
          padding: "64px 80px",
          textAlign: "center",
          border: t.cardBorder,
          boxShadow: t.cardShadow,
          overflow: "hidden",
          position: "relative",
          minWidth: 420,
        }}
      >
        {/* 顶部装饰线 */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: "25%",
            right: "25%",
            height: t.accentLineHeight,
            background: `linear-gradient(90deg, transparent, ${accentColor}, transparent)`,
            opacity: t.accentLineOpacity,
          }}
        />

        {/* 标题 */}
        <div
          style={{
            fontSize: 30,
            color: t.textLabel,
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
            marginBottom: 12,
            fontWeight: t.fontWeightBody,
            letterSpacing: 2,
          }}
        >
          {title}
        </div>

        {/* 大数字 */}
        <div
          style={{
            fontSize: 120,
            fontWeight: t.fontWeightTitle,
            color: t.textPrimary,
            transform: `scale(${valueScale})`,
            opacity: valueOpacity,
            lineHeight: 1,
            letterSpacing: -1,
          }}
        >
          {value}
          {unit && (
            <span style={{ fontSize: 40, marginLeft: 10, color: t.textSecondary, fontWeight: t.fontWeightBody }}>
              {unit}
            </span>
          )}
        </div>

        {/* 描述 */}
        {description && (
          <div
            style={{
              fontSize: 24,
              color: t.textSecondary,
              marginTop: 16,
              opacity: descOpacity,
              fontWeight: t.fontWeightBody,
            }}
          >
            {description}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
