import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface HighlightTextProps {
  text?: string;
  sub_text?: string;
  color?: string;
  position?: "center" | "top" | "bottom";
  font_size?: number;
  style?: StyleType;
}

export const HighlightText: React.FC<HighlightTextProps> = ({
  text = "",
  sub_text = "",
  color,
  position = "center",
  font_size = 72,
  style = "default",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = getTokens(style);

  const textColor = color || t.textPrimary;
  const chars = text.split("");

  // 整体弹入 — 用于装饰线
  const pop = spring({
    fps,
    frame,
    config: { stiffness: 50, damping: 16 },
  });

  // 副文本延迟
  const subPop = spring({
    fps,
    frame: frame - 15,
    config: { stiffness: 40, damping: 14 },
  });
  const subOpacity = interpolate(subPop, [0, 1], [0, 1]);
  const subY = interpolate(subPop, [0, 1], [15, 0]);

  // 退出淡出
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const justifyContent =
    position === "top" ? "flex-start" : position === "bottom" ? "flex-end" : "center";

  return (
    <AbsoluteFill
      style={{
        justifyContent,
        alignItems: "center",
        paddingTop: position === "top" ? 120 : 0,
        paddingBottom: position === "bottom" ? 80 : 0,
        paddingLeft: 60,
        paddingRight: 60,
        fontFamily: t.fontFamily,
        opacity: fadeOut,
      }}
    >
      <div style={{ textAlign: "center", maxWidth: "100%" }}>
        {/* 逐字弹出 */}
        <div style={{ display: "inline-flex", justifyContent: "center", flexWrap: "wrap", gap: 2 }}>
          {chars.map((char, i) => {
            const s = spring({
              fps,
              frame: frame - i * 2,
              config: { stiffness: 100, damping: 13 },
            });
            return (
              <span
                key={i}
                style={{
                  fontSize: font_size,
                  fontWeight: t.fontWeightTitle,
                  color: textColor,
                  opacity: interpolate(s, [0, 1], [0, 1]),
                  transform: `translateY(${interpolate(s, [0, 1], [30, 0])}px)`,
                  display: "inline-block",
                  letterSpacing: 2,
                  textShadow: "0 2px 8px rgba(0,0,0,0.3)",
                }}
              >
                {char}
              </span>
            );
          })}
        </div>

        {/* 装饰线 */}
        <div
          style={{
            width: interpolate(pop, [0, 1], [0, 320]),
            height: t.accentLineHeight,
            background: `linear-gradient(90deg, transparent, ${t.accentColor}, transparent)`,
            margin: "24px auto 0",
            borderRadius: 1,
            opacity: t.accentLineOpacity,
          }}
        />

        {/* 副文字 */}
        {sub_text && (
          <div
            style={{
              fontSize: Math.round(font_size * 0.42),
              color: t.textSecondary,
              marginTop: 14,
              opacity: subOpacity,
              transform: `translateY(${subY}px)`,
              fontWeight: t.fontWeightBody,
              letterSpacing: 2,
            }}
          >
            {sub_text}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
