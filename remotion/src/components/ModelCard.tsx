import { AbsoluteFill, interpolate, useCurrentFrame, spring, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface ModelCardProps {
  name?: string;
  downloads?: string;
  task?: string;
  description?: string;
  style?: StyleType;
}

export const ModelCard: React.FC<ModelCardProps> = ({
  name,
  downloads = "0",
  task = "text-generation",
  description = "",
  style = "default",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = getTokens(style);

  // 动画
  const slideIn = spring({ frame, fps, from: 50, to: 0, durationInFrames: 20 });
  const fadeIn = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [75, 90], [1, 0], { extrapolateLeft: "clamp" });

  // 下载量动画
  const downloadsText = String(downloads ?? "0");
  const dlNum = parseFloat(downloadsText.replace(/[^0-9.]/g, "")) || 0;
  const dlUnit = downloadsText.replace(/[0-9.]/g, "") || "";
  const counterProgress = interpolate(frame, [15, 45], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const displayDl = (dlNum * counterProgress).toFixed(dlNum >= 10 ? 0 : 1) + dlUnit;

  // 任务标签颜色
  const taskColor = 
    task.includes("generation") ? "#ff7b72" :
    task.includes("classification") ? "#79c0ff" :
    task.includes("detection") ? "#7ee787" :
    task.includes("translation") ? "#d2a8ff" :
    task.includes("embedding") ? "#ffa657" : "#8b949e";

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
          background: "linear-gradient(135deg, rgba(255,213,0,0.05) 0%, rgba(255,100,50,0.08) 100%)",
          borderRadius: t.cardBorderRadius,
          border: "1px solid rgba(255,213,0,0.2)",
          boxShadow: "0 8px 32px rgba(255,150,0,0.1)",
          transform: `translateY(${slideIn}px)`,
        }}
      >
        {/* HuggingFace Logo + 标题 */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 12,
              background: "linear-gradient(135deg, #FFD21E, #FF9D00)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 28,
            }}
          >
            🤗
          </div>
          <span
            style={{
              color: "rgba(255,255,255,0.95)",
              fontSize: 30,
              fontWeight: 700,
              fontFamily: t.fontFamily,
            }}
          >
            {name}
          </span>
        </div>

        {/* 任务标签 */}
        <div style={{ marginBottom: 20 }}>
          <span
            style={{
              display: "inline-block",
              padding: "6px 16px",
              borderRadius: 20,
              background: `${taskColor}22`,
              border: `1px solid ${taskColor}44`,
              color: taskColor,
              fontSize: 18,
              fontWeight: 500,
            }}
          >
            {task}
          </span>
        </div>

        {/* 描述 */}
        {description && (
          <p
            style={{
              color: "rgba(255,255,255,0.75)",
              fontSize: 22,
              lineHeight: 1.5,
              margin: "0 0 24px 0",
              fontFamily: t.fontFamily,
            }}
          >
            {description}
          </p>
        )}

        {/* 下载量 */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "16px 20px",
            background: "rgba(255,255,255,0.05)",
            borderRadius: 12,
            border: "1px solid rgba(255,255,255,0.1)",
          }}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="rgba(255,213,0,0.8)" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7,10 12,15 17,10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span style={{ color: "rgba(255,255,255,0.6)", fontSize: 20 }}>Downloads</span>
          <span
            style={{
              marginLeft: "auto",
              color: "#FFD21E",
              fontSize: 32,
              fontWeight: 700,
            }}
          >
            {displayDl}
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
