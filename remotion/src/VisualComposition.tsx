import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { CommentScroll } from "./components/CommentScroll";
import { DataReveal } from "./components/DataReveal";
import { InfoPanel } from "./components/InfoPanel";
import { HighlightText } from "./components/HighlightText";
import { QuoteBox } from "./components/QuoteBox";
import { CodeScroll } from "./components/CodeScroll";
import { StatsCard } from "./components/StatsCard";
import { ModelCard } from "./components/ModelCard";
import { RankingTable } from "./components/RankingTable";
import type { StyleType } from "./styles";

export interface VisualItem {
  start_ms: number;
  duration_ms: number;
  type: string; // "remotion" | "image" | "video_clip"
  component?: string;
  props?: Record<string, any>;
  source?: string;
  style?: StyleType;
}

export interface VisualCompositionProps extends Record<string, unknown> {
  visualItems: VisualItem[];
  background?: string[];
  style?: StyleType;
}

const FPS = 30;

function msToFrames(ms: number): number {
  return Math.round((ms / 1000) * FPS);
}

/**
 * 渲染 visual 轨中 type=remotion 的组件（带不透明背景）
 */
function renderVisualComponent(item: VisualItem, index: number, globalStyle: StyleType) {
  const props = item.props || {};
  const style = item.style || globalStyle;

  switch (item.component) {
    case "comment_scroll":
      return <CommentScroll key={index} {...props} style={style} />;
    case "data_reveal":
      return <DataReveal key={index} {...props} style={style} />;
    case "info_panel":
      return <InfoPanel key={index} {...props} style={style} />;
    case "highlight_text":
      return <HighlightText key={index} {...props} style={style} />;
    case "quote_box":
      return <QuoteBox key={index} {...props} style={style} />;
    case "code_scroll":
      return <CodeScroll key={index} {...props} style={style} />;
    case "stats_card":
      return <StatsCard key={index} {...props} style={style} />;
    case "model_card":
      return <ModelCard key={index} {...props} style={style} />;
    case "ranking_table":
      return <RankingTable key={index} {...props} style={style} />;
    default:
      // 未知组件 fallback 为 HighlightText
      return (
        <HighlightText
          key={index}
          text={props.title || props.text || ""}
          sub_text={props.subtitle || props.sub_text || ""}
          color={props.color || "#4ecdc4"}
          position="center"
          style={style}
        />
      );
  }
}

export const VisualComposition: React.FC<VisualCompositionProps> = ({
  visualItems,
  background = ["#0f0f23", "#1a1a3e"],
  style = "solid",
}) => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(135deg, ${background[0]} 0%, ${background[1]} 100%)`,
      }}
    >
      {visualItems.map((item, i) => {
        if (item.type !== "remotion") return null;

        // position 控制垂直位置，默认 top 避开底部 Live2D
        const position = item.props?.position || "top";
        const alignItems = position === "bottom" ? "flex-end" 
          : position === "center" ? "center" 
          : "flex-start";
        const paddingTop = position === "top" ? 120 : 0;
        const paddingBottom = position === "bottom" ? 400 : 0;

        return (
          <Sequence
            key={i}
            from={msToFrames(item.start_ms)}
            durationInFrames={msToFrames(item.duration_ms)}
          >
            <AbsoluteFill
              style={{
                display: "flex",
                alignItems,
                justifyContent: "center",
                paddingTop,
                paddingBottom,
              }}
            >
              {renderVisualComponent(item, i, style)}
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
