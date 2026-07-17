import { AbsoluteFill, interpolate, useCurrentFrame, spring, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface StatsCardProps {
  name?: string;
  stars?: string;
  forks?: string;
  language?: string;
  description?: string;
  style?: StyleType;
}

export const StatsCard: React.FC<StatsCardProps> = ({
  name,
  stars = "0",
  forks = "0",
  language = "Unknown",
  description = "",
  style = "default",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = getTokens(style);

  // 弹入动画
  const scaleIn = spring({ frame, fps, from: 0.8, to: 1, durationInFrames: 20 });
  const fadeIn = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [75, 90], [1, 0], { extrapolateLeft: "clamp" });

  // 数字递增动画
  const starsText = String(stars ?? "0");
  const forksText = String(forks ?? "0");
  const starsNum = parseFloat(starsText.replace(/[^0-9.]/g, "")) || 0;
  const starsUnit = starsText.replace(/[0-9.]/g, "") || "";
  const forksNum = parseFloat(forksText.replace(/[^0-9.]/g, "")) || 0;
  const forksUnit = forksText.replace(/[0-9.]/g, "") || "";
  
  const counterProgress = interpolate(frame, [10, 40], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  
  const displayStars = (starsNum * counterProgress).toFixed(1) + starsUnit;
  const displayForks = Math.round(forksNum * counterProgress) + forksUnit;

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
          width: "85%",
          padding: "40px",
          background: "rgba(13, 17, 23, 0.95)",
          borderRadius: t.cardBorderRadius,
          border: "1px solid rgba(48, 54, 61, 0.8)",
          boxShadow: t.cardShadow,
          transform: `scale(${scaleIn})`,
        }}
      >
        {/* 项目名 */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <svg width="28" height="28" viewBox="0 0 16 16" fill="rgba(255,255,255,0.7)">
            <path d="M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9z" />
          </svg>
          <span
            style={{
              color: "#58a6ff",
              fontSize: 32,
              fontWeight: 600,
              fontFamily: t.fontFamily,
            }}
          >
            {name}
          </span>
        </div>

        {/* 描述 */}
        {description && (
          <p
            style={{
              color: "rgba(255,255,255,0.7)",
              fontSize: 22,
              lineHeight: 1.5,
              margin: "0 0 24px 0",
              fontFamily: t.fontFamily,
            }}
          >
            {description}
          </p>
        )}

        {/* 统计 */}
        <div style={{ display: "flex", gap: 32, marginTop: 16 }}>
          {/* Stars */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <svg width="22" height="22" viewBox="0 0 16 16" fill="#e3b341">
              <path d="M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z" />
            </svg>
            <span style={{ color: "#e3b341", fontSize: 28, fontWeight: 700 }}>
              {displayStars}
            </span>
          </div>

          {/* Forks */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <svg width="22" height="22" viewBox="0 0 16 16" fill="rgba(255,255,255,0.6)">
              <path d="M5 3.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm0 2.122a2.25 2.25 0 10-1.5 0v.878A2.25 2.25 0 005.75 8.5h1.5v2.128a2.251 2.251 0 101.5 0V8.5h1.5a2.25 2.25 0 002.25-2.25v-.878a2.25 2.25 0 10-1.5 0v.878a.75.75 0 01-.75.75h-4.5A.75.75 0 015 6.25v-.878zm3.75 7.378a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm3-8.75a.75.75 0 100-1.5.75.75 0 000 1.5z" />
            </svg>
            <span style={{ color: "rgba(255,255,255,0.7)", fontSize: 28, fontWeight: 600 }}>
              {displayForks}
            </span>
          </div>

          {/* Language */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: "50%",
                background: language === "Python" ? "#3572A5" :
                  language === "TypeScript" ? "#3178c6" :
                  language === "JavaScript" ? "#f1e05a" :
                  language === "Rust" ? "#dea584" :
                  language === "Go" ? "#00ADD8" : "#8b949e",
              }}
            />
            <span style={{ color: "rgba(255,255,255,0.6)", fontSize: 22 }}>
              {language}
            </span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
