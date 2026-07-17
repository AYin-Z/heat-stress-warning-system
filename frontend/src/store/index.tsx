/**
 * 全局数据状态管理 — React Context
 */
import React, { createContext, useContext, useReducer, useCallback, type ReactNode } from 'react';
import type { VitalData, AlertPopupData, AlertRecord, MapMarker, Officer, RiskLevel } from '../types';
import { RiskLevel as RL, TEMP_THRESHOLDS } from '../types';

// ============================================================
// State
// ============================================================

interface AppState {
  // 设备数据
  devices: Record<string, VitalData>;       // deviceId → 最新数据
  onlineDevices: Set<string>;               // 在线设备集合
  officers: Record<string, Officer>;        // 人员信息（初始化后加载）

  // 预警
  alertRecords: AlertRecord[];
  activeAlert: AlertPopupData | null;       // 当前弹窗中的预警

  // UI
  selectedDeviceId: string | null;          // 选中的民警（详情弹窗）
  sidebarCollapsed: boolean;                // 侧边栏折叠
}

// ============================================================
// Actions
// ============================================================

type Action =
  | { type: 'VITAL_DATA'; payload: VitalData }
  | { type: 'DEVICE_ONLINE'; deviceId: string }
  | { type: 'DEVICE_OFFLINE'; deviceId: string }
  | { type: 'ALERT'; payload: AlertPopupData }
  | { type: 'ALERT_RECORD'; payload: AlertRecord }
  | { type: 'DISMISS_ALERT' }
  | { type: 'SELECT_DEVICE'; deviceId: string | null }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'REGISTER_OFFICER'; payload: Officer }
  | { type: 'CLEAR_RECORDS'; before?: number }; // 清除指定时间前的记录

// ============================================================
// Helper
// ============================================================

function getRiskLevel(data: VitalData): RiskLevel {
  if (
    data.worn === false ||
    data.dataQuality === 'not_worn' ||
    data.dataQuality === 'no_vitals'
  ) return RL.Unavailable;
  if (data.riskLevel && data.riskLevel !== RL.Normal) return data.riskLevel;
  if (data.coreTemp == null) return RL.Monitoring;
  if (data.coreTemp >= TEMP_THRESHOLDS.WARNING_MAX) return RL.HighRisk;
  if (data.coreTemp >= TEMP_THRESHOLDS.NORMAL_MAX) return RL.Warning;
  return RL.Normal;
}

// ============================================================
// Reducer
// ============================================================

const initialState: AppState = {
  devices: {},
  onlineDevices: new Set(),
  officers: {},
  alertRecords: [],
  activeAlert: null,
  selectedDeviceId: null,
  sidebarCollapsed: false,
};

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'VITAL_DATA': {
      const data = action.payload;
      // MQTT vital 是完整快照。直接替换可确保未佩戴后的缺失字段清除旧值。
      const riskLevel = getRiskLevel(data);
      return {
        ...state,
        devices: {
          ...state.devices,
          [data.deviceId]: { ...data, riskLevel },
        },
      };
    }

    case 'DEVICE_ONLINE':
      return {
        ...state,
        onlineDevices: new Set([...state.onlineDevices, action.deviceId]),
      };

    case 'DEVICE_OFFLINE': {
      const next = new Set(state.onlineDevices);
      next.delete(action.deviceId);
      return { ...state, onlineDevices: next };
    }

    case 'ALERT':
      // 将告警中的核心温度回写至对应设备，使其从"监测中"进入风险分级
      if (action.payload.coreTemp != null && state.devices[action.payload.deviceId]) {
        state = {
          ...state,
          devices: {
            ...state.devices,
            [action.payload.deviceId]: {
              ...state.devices[action.payload.deviceId],
              coreTemp: action.payload.coreTemp,
            },
          },
        };
      }
      return { ...state, activeAlert: action.payload };

    case 'ALERT_RECORD':
      return {
        ...state,
        alertRecords: [action.payload, ...state.alertRecords],
      };

    case 'DISMISS_ALERT':
      return { ...state, activeAlert: null };

    case 'SELECT_DEVICE':
      return { ...state, selectedDeviceId: action.deviceId };

    case 'TOGGLE_SIDEBAR':
      return { ...state, sidebarCollapsed: !state.sidebarCollapsed };

    case 'REGISTER_OFFICER': {
      const officer = action.payload;
      return {
        ...state,
        officers: { ...state.officers, [officer.deviceId]: officer },
      };
    }

    case 'CLEAR_RECORDS':
      return {
        ...state,
        alertRecords: action.before
          ? state.alertRecords.filter((r) => r.timestamp > action.before!)
          : [],
      };

    default:
      return state;
  }
}

// ============================================================
// Context
// ============================================================

interface AppContextValue {
  state: AppState;
  dispatch: React.Dispatch<Action>;
  // Derived data helpers
  getMarkers: () => MapMarker[];
  getRiskStats: () => {
    normal: number;
    warning: number;
    highRisk: number;
    monitoring: number;
    unavailable: number;
    offline: number;
  };
  getOfficerName: (deviceId: string) => string;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const getMarkers = useCallback((): MapMarker[] => {
    return Object.values(state.devices).filter(
      (d) => d.latitude != null && d.longitude != null
    ).map((d) => ({
      deviceId: d.deviceId,
      position: [d.longitude!, d.latitude!],
      name: state.officers[d.deviceId]?.name || d.deviceId,
      riskLevel: d.riskLevel || RL.Unavailable,
      vitalData: d,
    }));
  }, [state.devices, state.officers]);

  const getRiskStats = useCallback(() => {
    let normal = 0, warning = 0, highRisk = 0, monitoring = 0, unavailable = 0, offline = 0;
    const allDevices = new Set([
      ...Object.keys(state.devices),
      ...state.onlineDevices,
      // 只纳入曾经上线或有数据的 officer，避免纯注册未连接者计入"离线"
      ...Object.keys(state.officers).filter(
        (id) => state.devices[id] || state.onlineDevices.has(id)
      ),
    ]);

    allDevices.forEach((id) => {
      if (!state.onlineDevices.has(id)) {
        offline++;
        return;
      }
      const device = state.devices[id];
      switch (device?.riskLevel) {
        case RL.Normal: normal++; break;
        case RL.Warning: warning++; break;
        case RL.HighRisk: highRisk++; break;
        case RL.Monitoring: monitoring++; break;
        default: unavailable++;
      }
    });

    return { normal, warning, highRisk, monitoring, unavailable, offline };
  }, [state.devices, state.onlineDevices, state.officers]);

  const getOfficerName = useCallback(
    (deviceId: string) => state.officers[deviceId]?.name || deviceId,
    [state.officers]
  );

  return (
    <AppContext.Provider value={{ state, dispatch, getMarkers, getRiskStats, getOfficerName }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useAppState must be used within AppProvider');
  return ctx;
}
