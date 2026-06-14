import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { getTokens, type StyleType } from "../styles";

interface Comment {
  user: string;
  text: string;
  likes?: number;
}

interface CommentScrollProps {
  comments?: Comment[];
  direction?: "right_to_left" | "left_to_right";
  font_size?: number;
  opacity?: number;
  style?: StyleType;
}

export const CommentScroll: React.FC<CommentScrollProps> = ({
  comments: rawComments = [],
  direction = "right_to_left",
  font_size = 32,
  opacity = 0.9,
  style = "default",
}) => {
  // 兼容字符串数组（Director 生成）和对象数组
  const comments: Comment[] = rawComments.map((c: any, i: number) => {
    if (typeof c === "string") {
      const names = ["路人甲", "吃瓜群众", "热心网友", "围观大佬", "小明", "老王", "匿名", "刷屏侠"];
      return { user: names[i % names.length], text: c };
    }
    return c;
  });
  const frame = useCurrentFrame();
  const { width, durationInFrames } = useVideoConfig();
  const t = getTokens(style);

  return (
    <AbsoluteFill
      style={{
        overflow: "hidden",
        fontFamily: t.fontFamily,
      }}
    >
      {comments.map((comment, i) => {
        // 均匀错开入场 — 每条弹幕之间间隔总时长的 20%
        const staggerDelay = i * Math.floor(durationInFrames * 0.2);
        const elapsed = frame - staggerDelay;

        if (elapsed < 0) return null;

        // 每条弹幕用完整的 durationInFrames 来滚动
        const scrollDuration = durationInFrames;
        const progress = elapsed / scrollDuration;
        if (progress > 1.2) return null;

        const xStart = direction === "right_to_left" ? width + 50 : -(width * 0.6);
        const xEnd = direction === "right_to_left" ? -(width * 0.6) : width + 50;
        const x = interpolate(progress, [0, 1], [xStart, xEnd], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });

        // 垂直分布 — 在画面中部偏下
        const yBase = 600 + i * 180;

        // 淡入淡出
        const fadeIn = interpolate(elapsed, [0, 15], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const fadeOut = interpolate(progress, [0.85, 1], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: yBase,
              left: 0,
              transform: `translateX(${x}px)`,
              opacity: opacity * fadeIn * fadeOut,
              whiteSpace: "nowrap",
            }}
          >
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 10,
                background: t.bubbleBg,
                borderRadius: 22,
                padding: "14px 22px 14px 14px",
                border: t.bubbleBorder,
                backdropFilter: `blur(${Math.round(t.cardBlur * 0.6)}px)`,
              }}
            >
              {/* 头像 */}
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: "50%",
                  background: t.avatarColors[i % t.avatarColors.length],
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 18,
                  color: "#fff",
                  fontWeight: 600,
                  flexShrink: 0,
                }}
              >
                {comment.user.slice(0, 1)}
              </div>

              {/* 用户名 */}
              <span
                style={{
                  fontSize: font_size * 0.65,
                  color: t.textSecondary,
                  fontWeight: 500,
                }}
              >
                {comment.user}
              </span>

              {/* 文字 */}
              <span
                style={{
                  fontSize: font_size,
                  color: t.textPrimary,
                  fontWeight: t.fontWeightBody,
                }}
              >
                {comment.text}
              </span>

              {/* 点赞 */}
              {comment.likes && comment.likes > 0 ? (
                <span
                  style={{
                    fontSize: font_size * 0.55,
                    color: t.textSecondary,
                    marginLeft: 4,
                  }}
                >
                  ♥ {comment.likes}
                </span>
              ) : null}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
