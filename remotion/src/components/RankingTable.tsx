import { AbsoluteFill, interpolate, useCurrentFrame, spring, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface RankingItem {
  rank: number;
  name: string;
  value: string;
}

interface RankingTableProps {
  title?: string;
  items?: RankingItem[];
  style?: StyleType;
}

export const RankingTable: React.FC<RankingTableProps> = ({
  title,
  items = [],
  style = "default",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = getTokens(style);

  const fadeIn = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [75, 90], [1, 0], { extrapolateLeft: "clamp" });

  // 标题弹入
  const titleScale = spring({ frame, fps, from: 0.8, to: 1, durationInFrames: 15 });

  // 排名奖牌颜色
  const medalColor = (rank: number) => {
    if (rank === 1) return "#FFD700";
    if (rank === 2) return "#C0C0C0";
    if (rank === 3) return "#CD7F32";
    return "rgba(255,255,255,0.4)";
  };

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeIn * fadeOut,
      }}
    >
      <div
        style={{
          width: "88%",
          padding: "32px",
          background: t.cardBg,
          borderRadius: t.cardBorderRadius,
          border: t.cardBorder,
          boxShadow: t.cardShadow,
          backdropFilter: `blur(${t.cardBlur}px)`,
        }}
      >
        {/* 标题 */}
        <div
          style={{
            textAlign: "center",
            marginBottom: 24,
            transform: `scale(${titleScale})`,
          }}
        >
          <span style={{ fontSize: 20, color: t.textSecondary }}>🏆</span>
          <h2
            style={{
              color: t.textPrimary,
              fontSize: 28,
              fontWeight: t.fontWeightTitle,
              fontFamily: t.fontFamily,
              margin: "8px 0 0 0",
            }}
          >
            {title}
          </h2>
        </div>

        {/* 排行列表 */}
        {items.slice(0, 8).map((item, i) => {
          // 每行逐个滑入
          const rowDelay = 8 + i * 4;
          const rowSlide = spring({
            frame: Math.max(0, frame - rowDelay),
            fps,
            from: 60,
            to: 0,
            durationInFrames: 15,
          });
          const rowOpacity = interpolate(frame, [rowDelay, rowDelay + 8], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "12px 16px",
                marginBottom: 4,
                borderRadius: 12,
                background: i % 2 === 0 ? "rgba(255,255,255,0.03)" : "transparent",
                opacity: rowOpacity,
                transform: `translateX(${rowSlide}px)`,
              }}
            >
              {/* 排名 */}
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  background: item.rank <= 3
                    ? `${medalColor(item.rank)}22`
                    : "rgba(255,255,255,0.05)",
                  border: `2px solid ${medalColor(item.rank)}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 16,
                  fontWeight: 700,
                  color: medalColor(item.rank),
                  marginRight: 16,
                  flexShrink: 0,
                }}
              >
                {item.rank}
              </div>

              {/* 名称 */}
              <span
                style={{
                  flex: 1,
                  color: t.textPrimary,
                  fontSize: 20,
                  fontWeight: 500,
                  fontFamily: t.fontFamily,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {item.name}
              </span>

              {/* 数值 */}
              <span
                style={{
                  color: t.accentColor,
                  fontSize: 20,
                  fontWeight: 600,
                  marginLeft: 12,
                  flexShrink: 0,
                }}
              >
                {item.value}
              </span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
