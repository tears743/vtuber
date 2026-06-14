/**
 * 风格系统 — 根据 style 字段切换视觉主题
 *
 * "default" = 极简 × 毛玻璃（用于 overlay 层，下方有视频）
 * "solid"   = 实底高对比（用于 visual 层，深色背景上）
 * "kawaii"  = 粉紫可爱
 */

export type StyleType = "default" | "solid" | "kawaii";

export interface StyleTokens {
  // 卡片
  cardBg: string;
  cardBorder: string;
  cardBorderRadius: number;
  cardShadow: string;
  cardBlur: number;

  // 文字
  textPrimary: string;
  textSecondary: string;
  textLabel: string;
  fontFamily: string;
  fontWeightTitle: number;
  fontWeightBody: number;

  // 装饰
  accentColor: string;
  accentLineHeight: number;
  accentLineOpacity: number;

  // 弹幕
  bubbleBg: string;
  bubbleBorder: string;
  avatarColors: string[];
}

const defaultTokens: StyleTokens = {
  cardBg: "rgba(255,255,255,0.15)",
  cardBorder: "1px solid rgba(255,255,255,0.25)",
  cardBorderRadius: 20,
  cardShadow: "0 8px 32px rgba(0,0,0,0.3)",
  cardBlur: 16,

  textPrimary: "rgba(255,255,255,0.95)",
  textSecondary: "rgba(255,255,255,0.75)",
  textLabel: "rgba(255,255,255,0.6)",
  fontFamily: "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  fontWeightTitle: 600,
  fontWeightBody: 400,

  accentColor: "rgba(130,180,255,0.85)",
  accentLineHeight: 2,
  accentLineOpacity: 0.8,

  bubbleBg: "rgba(255,255,255,0.12)",
  bubbleBorder: "1px solid rgba(255,255,255,0.15)",
  avatarColors: [
    "linear-gradient(135deg, #64748b, #475569)",
    "linear-gradient(135deg, #6b7280, #4b5563)",
    "linear-gradient(135deg, #78716c, #57534e)",
    "linear-gradient(135deg, #71717a, #52525b)",
    "linear-gradient(135deg, #6b7280, #374151)",
  ],
};

const solidTokens: StyleTokens = {
  cardBg: "rgba(30, 40, 70, 0.95)",
  cardBorder: "1px solid rgba(100, 150, 255, 0.4)",
  cardBorderRadius: 20,
  cardShadow: "0 8px 40px rgba(0,0,0,0.5), 0 0 60px rgba(80,120,255,0.1)",
  cardBlur: 0,

  textPrimary: "#ffffff",
  textSecondary: "rgba(200, 220, 255, 0.85)",
  textLabel: "rgba(160, 190, 255, 0.9)",
  fontFamily: "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  fontWeightTitle: 700,
  fontWeightBody: 400,

  accentColor: "#6ea8fe",
  accentLineHeight: 3,
  accentLineOpacity: 1.0,

  bubbleBg: "rgba(40, 60, 100, 0.9)",
  bubbleBorder: "1px solid rgba(100, 150, 255, 0.3)",
  avatarColors: [
    "linear-gradient(135deg, #4f87e6, #2563eb)",
    "linear-gradient(135deg, #7c3aed, #6d28d9)",
    "linear-gradient(135deg, #06b6d4, #0891b2)",
    "linear-gradient(135deg, #10b981, #059669)",
    "linear-gradient(135deg, #f59e0b, #d97706)",
  ],
};

const kawaiiTokens: StyleTokens = {
  cardBg: "linear-gradient(135deg, rgba(180,130,255,0.15) 0%, rgba(255,150,200,0.12) 100%)",
  cardBorder: "1px solid rgba(200,150,255,0.2)",
  cardBorderRadius: 24,
  cardShadow: "0 8px 32px rgba(160,100,220,0.15)",
  cardBlur: 12,

  textPrimary: "rgba(255,255,255,0.95)",
  textSecondary: "rgba(230,200,255,0.7)",
  textLabel: "rgba(220,180,255,0.5)",
  fontFamily: "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  fontWeightTitle: 700,
  fontWeightBody: 400,

  accentColor: "rgba(220,160,255,0.8)",
  accentLineHeight: 3,
  accentLineOpacity: 0.7,

  bubbleBg: "linear-gradient(135deg, rgba(200,150,255,0.12) 0%, rgba(255,180,200,0.1) 100%)",
  bubbleBorder: "1px solid rgba(220,170,255,0.15)",
  avatarColors: [
    "linear-gradient(135deg, #c084fc, #a855f7)",
    "linear-gradient(135deg, #f472b6, #ec4899)",
    "linear-gradient(135deg, #a78bfa, #8b5cf6)",
    "linear-gradient(135deg, #67e8f9, #22d3ee)",
    "linear-gradient(135deg, #fda4af, #fb7185)",
  ],
};

export function getTokens(style: StyleType = "default"): StyleTokens {
  switch (style) {
    case "solid":
      return solidTokens;
    case "kawaii":
      return kawaiiTokens;
    default:
      return defaultTokens;
  }
}

