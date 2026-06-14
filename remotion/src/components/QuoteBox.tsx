import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface QuoteBoxProps {
  text?: string;
  quote?: string;
  source?: string;
  color?: string;
  style?: StyleType;
}

export const QuoteBox: React.FC<QuoteBoxProps> = (props) => {
  const {
    source = "",
    color,
    style = "default",
  } = props;
  // 兼容 Director 格式: {quote} → {text}
  const text = props.text || props.quote || "";
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = getTokens(style);

  const accent = color || t.accentColor;

  // 淡入
  const fadeIn = spring({
    fps,
    frame,
    config: { stiffness: 40, damping: 15 },
  });
  const cardOpacity = interpolate(fadeIn, [0, 1], [0, 1]);
  const cardY = interpolate(fadeIn, [0, 1], [15, 0]);

  // 淡出
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // source 延迟
  const srcOpacity = interpolate(frame, [20, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 60,
        fontFamily: t.fontFamily,
      }}
    >
      <div
        style={{
          background: t.cardBg,
          backdropFilter: `blur(${t.cardBlur}px)`,
          borderRadius: t.cardBorderRadius,
          padding: "48px 52px",
          maxWidth: 750,
          opacity: cardOpacity * fadeOut,
          transform: `translateY(${cardY}px)`,
          borderLeft: `3px solid ${accent}`,
          border: t.cardBorder,
          borderLeftWidth: 3,
          borderLeftColor: accent as string,
          borderLeftStyle: "solid",
          boxShadow: t.cardShadow,
        }}
      >
        {/* 引用文字 */}
        <div
          style={{
            fontSize: 30,
            color: t.textPrimary,
            lineHeight: 1.7,
            fontWeight: t.fontWeightBody,
          }}
        >
          {text}
        </div>

        {/* 来源 */}
        {source && (
          <div
            style={{
              fontSize: 20,
              color: t.textSecondary,
              marginTop: 16,
              textAlign: "right",
              fontWeight: 500,
              opacity: srcOpacity,
            }}
          >
            — {source}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
