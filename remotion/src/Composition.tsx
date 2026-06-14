import { AbsoluteFill, Sequence } from "remotion";
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

export interface OverlayItem {
  start_ms: number;
  duration_ms: number;
  type: string;
  description?: string;
  style?: StyleType;
  props?: Record<string, any>;
  // 通用布局控制
  scale?: number;          // 整体缩放，默认 1.0
  position?: string;       // "center" | "top" | "bottom" | "top-left" | "bottom-right" 等
  offsetX?: number;        // 水平偏移 px
  offsetY?: number;        // 垂直偏移 px
}

export interface CompositionProps extends Record<string, unknown> {
  overlayItems: OverlayItem[];
  style?: StyleType;
}

const FPS = 30;

function msToFrames(ms: number): number {
  return Math.round((ms / 1000) * FPS);
}

/**
 * 将 position 字符串转为 CSS justify/align
 */
function getPositionStyles(pos: string): React.CSSProperties {
  const styles: React.CSSProperties = {
    display: "flex",
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  };

  // 垂直
  if (pos.includes("top")) {
    styles.alignItems = "flex-start";
    styles.paddingTop = 80;
  } else if (pos.includes("bottom")) {
    styles.alignItems = "flex-end";
    styles.paddingBottom = 80;
  } else {
    styles.alignItems = "center";
  }

  // 水平
  if (pos.includes("left")) {
    styles.justifyContent = "flex-start";
    styles.paddingLeft = 40;
  } else if (pos.includes("right")) {
    styles.justifyContent = "flex-end";
    styles.paddingRight = 40;
  } else {
    styles.justifyContent = "center";
  }

  return styles;
}

function renderOverlayItem(item: OverlayItem, index: number, globalStyle: StyleType) {
  const props = item.props || {};
  const style = item.style || globalStyle;

  switch (item.type) {
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
      return null;
  }
}

export const OverlayComposition: React.FC<CompositionProps> = ({
  overlayItems,
  style = "default",
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      {overlayItems.map((item, i) => {
        const scale = item.scale ?? 1.0;
        const offsetX = item.offsetX ?? 0;
        const offsetY = item.offsetY ?? 0;

        // 只有 scale != 1 或有 offset 时才应用 transform
        const needsTransform = scale !== 1.0 || offsetX !== 0 || offsetY !== 0;

        return (
          <Sequence
            key={i}
            from={msToFrames(item.start_ms)}
            durationInFrames={msToFrames(item.duration_ms)}
          >
            {needsTransform ? (
              <AbsoluteFill
                style={{
                  transform: `scale(${scale}) translate(${offsetX}px, ${offsetY}px)`,
                  transformOrigin: "center center",
                }}
              >
                {renderOverlayItem(item, i, style)}
              </AbsoluteFill>
            ) : (
              renderOverlayItem(item, i, style)
            )}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
