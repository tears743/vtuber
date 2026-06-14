/**
 * Live2D Composition — Remotion 离线渲染
 *
 * 核心策略：
 * 1. 用 delayRender/continueRender 等待模型加载
 * 2. 用 useCurrentFrame() 手动驱动动画（替代 requestAnimationFrame）
 * 3. 从 props.volumes[] 计算当前帧嘴巴开合度
 * 4. 透明背景输出 WebM
 */
import { AbsoluteFill, useCurrentFrame, useVideoConfig, delayRender, continueRender, staticFile } from "remotion";
import { useEffect, useRef, useState, useCallback } from "react";

// 注意：pixi.js 和 pixi-live2d-display 需要在浏览器环境中加载
// Remotion 的 headless Chrome 提供了这个环境

interface ActionTimelineEntry {
  startFrame: number;
  action: string;
  expression?: string | null;
  motion?: { group: string; index: number } | null;
}

export interface Live2DProps extends Record<string, unknown> {
  modelUrl: string;          // model3.json 的相对路径（public/ 下）
  volumes: number[];         // 每帧的嘴巴音量 (0-1)，长度 = durationInFrames
  expressions?: string[];    // 按帧触发表情 [{frame, expression}]
  motions?: Array<{ frame: number; group: string; index?: number }>;
  initialMotion?: { group: string; index: number };  // 初始动作
  initialExpression?: string;  // 初始表情
  actionTimeline?: ActionTimelineEntry[];  // action 时间线
  scale?: number;
  offsetX?: number;
  offsetY?: number;
}

export const Live2DComposition: React.FC<Live2DProps> = ({
  modelUrl,
  volumes = [],
  expressions = [],
  motions = [],
  initialMotion,
  initialExpression,
  actionTimeline = [],
  scale = 0.5,
  offsetX = 0,
  offsetY = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const appRef = useRef<any>(null);
  const currentActionRef = useRef<string>("");
  const modelRef = useRef<any>(null);
  const [handle] = useState(() => delayRender("Loading Live2D model"));

  // 通过 staticFile() 获取正确的 URL
  const resolvedModelUrl = staticFile(modelUrl);
  const cubismCoreUrl = staticFile("live2d/live2dcubismcore.min.js");

  const initLive2D = useCallback(async () => {
    if (!canvasRef.current) return;

    try {
      // 1. 动态加载 Cubism Core（必须先于 pixi-live2d-display）
      if (!(window as any).Live2DCubismCore) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script");
          script.src = cubismCoreUrl;
          script.onload = () => {
            console.log("[live2d-remotion] cubism core loaded");
            resolve();
          };
          script.onerror = (e) => {
            console.error("[live2d-remotion] cubism core failed:", cubismCoreUrl);
            reject(e);
          };
          document.head.appendChild(script);
        });
      }

      // 2. 动态导入 PixiJS
      const PIXI = await import("pixi.js");
      (window as any).PIXI = PIXI;

      // 3. 导入 Cubism 4 支持
      const { Live2DModel } = await import("pixi-live2d-display/cubism4");
      Live2DModel.registerTicker(PIXI.Ticker as any);

      // 创建 Pixi Application
      const app = new PIXI.Application({
        view: canvasRef.current,
        width,
        height,
        backgroundAlpha: 0, // 透明背景（special动作在compose阶段处理）
        antialias: true,
        resolution: 1,
        preserveDrawingBuffer: true, // 关键！否则 Remotion 截图为空
      });
      appRef.current = app;

      // 禁用自动 ticker（我们手动驱动）
      app.ticker.autoStart = false;
      app.ticker.stop();

      // 加载模型
      console.log("[live2d-remotion] loading model:", resolvedModelUrl);
      const model = await Live2DModel.from(resolvedModelUrl, {
        autoInteract: false,
        autoUpdate: false,
      });

      // 禁用事件
      model.eventMode = "none";
      model.interactiveChildren = false;

      // 修复特效渲染：设置 premultiplied alpha
      const internalRenderer = (model.internalModel as any)?.renderer;
      if (internalRenderer && typeof internalRenderer.setIsPremultipliedAlpha === "function") {
        internalRenderer.setIsPremultipliedAlpha(true);
      } else if (internalRenderer) {
        // 尝试直接赋值（不同版本 API 不同）
        try { internalRenderer._isPremultipliedAlpha = true; } catch {}
      }

      // 设置位置和缩放
      const origH = (model.height / (model.scale.y || 1)) || 1;
      const origW = (model.width / (model.scale.x || 1)) || 1;
      const baseScale = (height / origH) * scale;
      model.scale.set(baseScale);

      const scaledW = origW * baseScale;
      const scaledH = origH * baseScale;
      model.x = (width - scaledW) / 2 + offsetX;
      model.y = height - scaledH + offsetY;

      app.stage.addChild(model as any);
      modelRef.current = model;

      // 查找嘴巴参数
      const coreModel = (model.internalModel as any)?.coreModel;
      if (coreModel) {
        const params = coreModel._model?.parameters;
        if (params?.ids) {
          const names = Array.from(params.ids).map(String);
          const patterns = [/mouthopen/i, /mouth_open/i, /^ParamA$/i, /moutha/i];
          let mouthIdx = -1;
          for (const p of patterns) {
            const idx = names.findIndex((n: string) => p.test(n));
            if (idx >= 0) {
              mouthIdx = idx;
              break;
            }
          }
          if (mouthIdx < 0) {
            const fb = names.findIndex((n: string) => /mouth/i.test(n));
            if (fb >= 0) mouthIdx = fb;
          }

          if (mouthIdx >= 0) {
            // 存储嘴巴参数索引（直接写 parameters.values 数组用）
            (model as any).__mouthIdx = mouthIdx;
            (model as any).__mouthParamId = names[mouthIdx];
            console.log("[live2d-remotion] mouth param found:", names[mouthIdx], "at index:", mouthIdx);

            // 注册 beforeModelUpdate 事件：在 coreModel.update() 之前注入嘴巴值
            // 这是 motion/physics/pose 全部完成后、绘制数据计算前的最后时机
            (model.internalModel as any).on("beforeModelUpdate", () => {
              const mouthVal = (model as any).__currentMouthValue || 0;
              const cm = (model.internalModel as any)?.coreModel;
              if (cm) {
                const paramVals = cm._model?.parameters?.values;
                if (paramVals && mouthIdx < paramVals.length) {
                  paramVals[mouthIdx] = mouthVal;
                }
              }
            });
          }
        }
      }

      // 播放初始动作 — 根据当前 frame 从 actionTimeline 查找
      try {
        let initAction: ActionTimelineEntry | null = null;
        if (actionTimeline.length > 0) {
          for (let i = actionTimeline.length - 1; i >= 0; i--) {
            if (frame >= actionTimeline[i].startFrame) {
              initAction = actionTimeline[i];
              break;
            }
          }
        }
        
        if (initAction) {
          if (initAction.motion) {
            model.motion(initAction.motion.group, initAction.motion.index, 3);
          } else {
            model.motion("Idle", 0, 3);
          }
          if (initAction.expression) {
            model.expression(initAction.expression);
          }
        } else if (initialMotion) {
          model.motion(initialMotion.group, initialMotion.index, 3);
        } else {
          model.motion("Idle", 0, 3);
        }
      } catch {
        // ignore
      }

      // 设置初始表情（仅当没有 actionTimeline 时）
      if (initialExpression && actionTimeline.length === 0) {
        try {
          model.expression(initialExpression);
        } catch {
          // ignore
        }
      }

      console.log("[live2d-remotion] model loaded successfully");
      continueRender(handle);
    } catch (e) {
      console.error("[live2d-remotion] failed to load:", e);
      continueRender(handle);
    }
  }, [resolvedModelUrl, cubismCoreUrl, width, height, scale, offsetX, offsetY, handle]);

  // 初始化
  useEffect(() => {
    initLive2D();
    return () => {
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
    };
  }, [initLive2D]);

  // 每帧更新
  useEffect(() => {
    const model = modelRef.current;
    const app = appRef.current;
    if (!model || !app) return;

    // 0. 检查 actionTimeline，切换动作/表情
    if (actionTimeline.length > 0) {
      // 找到当前帧对应的 action entry（精确匹配 startFrame）
      const exactEntry = actionTimeline.find(e => e.startFrame === frame);
      if (exactEntry) {
        console.log(`[live2d-remotion] frame=${frame} trigger action: ${exactEntry.action}`);
        try {
          if (exactEntry.motion) {
            // priority=3 (FORCE) 强制覆盖当前播放的motion
            model.motion(exactEntry.motion.group, exactEntry.motion.index, 3);
          }
          if (exactEntry.expression) {
            model.expression(exactEntry.expression);
          }
        } catch (err) {
          console.error("[live2d-remotion] action error:", err);
        }
      }
    }

    // 1. 设置当前帧的嘴巴音量值（供 beforeModelUpdate 回调读取）
    const mouthIdx = (model as any).__mouthIdx;
    if (mouthIdx >= 0 && volumes.length > 0) {
      const vol = volumes[Math.min(frame, volumes.length - 1)] || 0;
      (model as any).__currentMouthValue = Math.min(1.0, vol * 2.5);
    } else {
      (model as any).__currentMouthValue = 0;
    }

    // 2. 手动以固定步长推进模型动画
    const dt = 1000 / fps;  // 毫秒
    model.update(dt);

    // 3. 渲染
    app.renderer.render(app.stage);
  }, [frame, fps, volumes, actionTimeline]);

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        style={{
          width: "100%",
          height: "100%",
          position: "absolute",
          top: 0,
          left: 0,
        }}
      />
    </AbsoluteFill>
  );
};
