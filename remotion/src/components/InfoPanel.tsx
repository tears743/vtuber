import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface InfoPanelProps {
  title?: string;
  points?: string[];
  items?: string[];
  description?: string;
  accent_color?: string;
  style?: StyleType;
}

export const InfoPanel: React.FC<InfoPanelProps> = ({
  title = "",
  points,
  items,
  description = "",
  accent_color,
  style = "default",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = getTokens(style);

  const accent = accent_color || t.accentColor;
  const list = points || items || [];

  // 面板整体滑入
  const slideIn = spring({
    fps,
    frame,
    config: { stiffness: 45, damping: 14, mass: 1.1 },
  });
  const panelX = interpolate(slideIn, [0, 1], [200, 0]);
  const panelOpacity = interpolate(slideIn, [0, 1], [0, 1]);

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
        alignItems: "flex-end",
        paddingRight: 40,
        fontFamily: t.fontFamily,
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          background: t.cardBg,
          backdropFilter: `blur(${t.cardBlur}px)`,
          borderRadius: t.cardBorderRadius,
          padding: "40px 44px",
          maxWidth: 680,
          transform: `translateX(${panelX}px)`,
          opacity: panelOpacity,
          border: t.cardBorder,
          boxShadow: t.cardShadow,
        }}
      >
        {/* 标题 */}
        <div
          style={{
            fontSize: 34,
            fontWeight: t.fontWeightTitle,
            color: t.textPrimary,
            marginBottom: 18,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              width: 4,
              height: 26,
              borderRadius: 2,
              background: accent,
              opacity: 0.8,
            }}
          />
          {title}
        </div>

        {/* 描述 */}
        {description && (
          <div
            style={{
              fontSize: 22,
              color: t.textSecondary,
              marginBottom: 14,
              lineHeight: 1.5,
            }}
          >
            {description}
          </div>
        )}

        {/* 列表 */}
        {list.map((item, i) => {
          const itemSpring = spring({
            fps,
            frame: frame - 8 - i * 5,
            config: { stiffness: 70, damping: 13 },
          });
          const itemOpacity = interpolate(itemSpring, [0, 1], [0, 1]);
          const itemX = interpolate(itemSpring, [0, 1], [20, 0]);

          return (
            <div
              key={i}
              style={{
                fontSize: 26,
                color: t.textPrimary,
                marginBottom: 12,
                opacity: itemOpacity,
                transform: `translateX(${itemX}px)`,
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                lineHeight: 1.4,
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: accent,
                  marginTop: 8,
                  flexShrink: 0,
                  opacity: 0.7,
                }}
              />
              <span style={{ fontWeight: t.fontWeightBody }}>{item}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
