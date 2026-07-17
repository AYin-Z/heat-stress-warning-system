// ============================================================
// 热应激预警系统 — 类型定义
// ============================================================

/** 风险等级 */
export const RiskLevel = {
  Normal: 'normal',
  Warning: 'warning',
  HighRisk: 'high_risk',
  Monitoring: 'monitoring',
  Unavailable: 'unavailable',
  Offline: 'offline',
} as const;
export type RiskLevel = (typeof RiskLevel)[keyof typeof RiskLevel];

/** 预警类型 */
export const AlertType = {
  Warning: '普通预警',
  HighRisk: '高风险预警',
} as const;
export type AlertType = (typeof AlertType)[keyof typeof AlertType];

/** 核心温度阈值 */
export const TEMP_THRESHOLDS = {
  NORMAL_MAX: 38,
  WARNING_MAX: 39,
} as const;

/** 设备在线状态 */
export const DeviceStatus = {
  Online: 'online',
  Offline: 'offline',
} as const;
export type DeviceStatus = (typeof DeviceStatus)[keyof typeof DeviceStatus];

// ============================================================
// 民警/设备
// ============================================================

export interface Officer {
  deviceId: string;         // 设备ID（资产编码）
  name: string;             // 姓名
  policeId?: string;        // 警号
  age?: number;             // 年龄
  gender?: '男' | '女';     // 性别
}

// ============================================================
// 实时生理数据（从手表 MQTT 上报）
// ============================================================

export interface VitalData {
  deviceId: string;
  timestamp: number;        // Unix 毫秒

  // 定位
  latitude?: number;
  longitude?: number;
  gpsAccuracy?: number;
  locationName?: string;    // 逆地理编码结果

  // 生理
  heartRate?: number;       // 心率 bpm；未佩戴或无有效采样时缺省
  spo2?: number;            // 血氧 %；未测得时缺省
  bloodPressure?: string;   // 血压 "120/80" mmHg；未测得时缺省
  steps?: number;           // 开机以来累计步数
  batteryLevel?: number;
  worn?: boolean;
  dataQuality?: 'complete' | 'partial' | 'not_worn' | 'no_vitals';
  firmwareVersion?: string;

  // 服务端计算结果（有延迟）
  coreTemp?: number;        // 核心温度预测值 ℃
  riskLevel?: RiskLevel;
  advice?: string;          // 大模型生成的两行建议

  // 客户端计算
  stepRate?: number;        // 步频（步/分钟）
}

// ============================================================
// 预警记录
// ============================================================

export interface AlertRecord {
  id: string;
  timestamp: number;        // 触发时间 Unix 毫秒
  deviceId: string;
  officerName: string;
  coreTemp?: number;        // 触发时核心温度；后端未提供时缺省
  alertType: AlertType;
}

// ============================================================
// 预警弹窗
// ============================================================

export interface AlertPopupData {
  deviceId: string;
  officerName: string;
  coreTemp?: number;
  alertType: AlertType;
  advice?: string;
}

// ============================================================
// 项目（后台管理用）
// ============================================================

export interface Project {
  id: string;
  name: string;
  status: 'recording' | 'stopped' | 'archived';
  createdAt: number;
}

// ============================================================
// MQTT 相关
// ============================================================

export interface MqttConfig {
  url: string;              // ws://39.105.86.77:8083/mqtt
  clientId: string;
  topics: {
    vital: string;          // 生理数据 topic
    alert: string;          // 预警 topic
    status: string;         // 设备在线状态 topic
  };
}

// ============================================================
// 地图标记
// ============================================================

export interface MapMarker {
  deviceId: string;
  position: [number, number]; // [lng, lat]
  name: string;
  riskLevel: RiskLevel;
  vitalData?: VitalData;
}
