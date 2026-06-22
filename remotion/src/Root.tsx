import { Composition } from "remotion";
import { OverlayComposition } from "./Composition";
import { VisualComposition } from "./VisualComposition";
import { Live2DComposition } from "./Live2DComposition";
import { MeteorOverlay } from "./MeteorOverlay";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Overlay"
        component={OverlayComposition}
        durationInFrames={30 * 1800}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          overlayItems: [],
        }}
      />
      <Composition
        id="Visual"
        component={VisualComposition}
        durationInFrames={30 * 1800}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          visualItems: [],
          background: ["#0f0f23", "#1a1a3e"],
        }}
      />
      <Composition
        id="Live2D"
        component={Live2DComposition}
        durationInFrames={30 * 1800}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          modelUrl: "/live2d/mao_pro/mao_pro.model3.json",
          volumes: [],
          scale: 0.5,
          offsetX: 0,
          offsetY: 0,
        }}
      />
      <Composition
        id="MeteorFx"
        component={MeteorOverlay}
        durationInFrames={30 * 10}
        fps={30}
        width={1080}
        height={1920}
      />
    </>
  );
};
