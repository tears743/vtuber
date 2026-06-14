import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface CodeScrollProps {
  code?: string;
  language?: string;
  title?: string;
  style?: StyleType;
}

export const CodeScroll: React.FC<CodeScrollProps> = ({
  code = "// no code provided",
  language = "python",
  title = "code.py",
  style = "default",
}) => {
  const frame = useCurrentFrame();
  const t = getTokens(style);

  const lines = code.split("\n");
  const totalLines = lines.length;
  
  // 滚动效果：从下往上滚动代码
  const scrollProgress = interpolate(frame, [0, 90], [0, 1], {
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(scrollProgress, [0, 1], [100, -totalLines * 24 + 600]);
  
  // 淡入
  const fadeIn = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  // 淡出
  const fadeOut = interpolate(frame, [80, 90], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeIn * fadeOut,
      }}
    >
      {/* 代码容器 */}
      <div
        style={{
          width: "90%",
          height: "65%",
          background: "rgba(20, 20, 35, 0.95)",
          borderRadius: t.cardBorderRadius,
          border: t.cardBorder,
          boxShadow: t.cardShadow,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* 标题栏 */}
        <div
          style={{
            padding: "16px 24px",
            borderBottom: "1px solid rgba(255,255,255,0.1)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          {/* 圆点 */}
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e" }} />
            <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
          </div>
          <span
            style={{
              color: "rgba(255,255,255,0.6)",
              fontSize: 16,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            }}
          >
            {title}
          </span>
          <span
            style={{
              marginLeft: "auto",
              color: "rgba(255,255,255,0.3)",
              fontSize: 14,
            }}
          >
            {language}
          </span>
        </div>
        
        {/* 代码内容（滚动） */}
        <div
          style={{
            flex: 1,
            padding: "20px 24px",
            overflow: "hidden",
            position: "relative",
          }}
        >
          <div
            style={{
              transform: `translateY(${translateY}px)`,
              fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
              fontSize: 18,
              lineHeight: "28px",
              color: "rgba(255,255,255,0.9)",
              whiteSpace: "pre",
            }}
          >
            {lines.map((line, i) => {
              const lineOpacity = interpolate(
                frame,
                [i * 2, i * 2 + 10],
                [0.3, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              return (
                <div key={i} style={{ opacity: lineOpacity }}>
                  <span style={{ color: "rgba(255,255,255,0.3)", marginRight: 16 }}>
                    {String(i + 1).padStart(3, " ")}
                  </span>
                  {line}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
