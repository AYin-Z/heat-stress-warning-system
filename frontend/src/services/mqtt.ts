import mqtt from 'mqtt';
import type { MqttClient } from 'mqtt';
import { AlertType, type AlertPopupData, type AlertRecord, type VitalData } from '../types';

const BROKER_URL = import.meta.env.VITE_MQTT_BROKER_URL || 'ws://39.105.86.77:8083/mqtt';
const MQTT_USERNAME = import.meta.env.VITE_MQTT_USERNAME || '';
const MQTT_PASSWORD = import.meta.env.VITE_MQTT_PASSWORD || '';
const OFFLINE_AFTER_MS = 90_000;

const TOPICS = {
  vital: 'watch/+/vital',
  alert: 'watch/+/alert',
  status: 'watch/+/status',
  coreTemp: 'watch/+/core-temp',
};

export type OnVitalData = (data: VitalData) => void;
export type OnAlert = (data: AlertPopupData) => void;
export type OnAlertRecord = (record: AlertRecord) => void;
export type OnStatusChange = (deviceId: string, online: boolean) => void;
export type OnCoreTemp = (deviceId: string, coreTemp: number) => void;

class MqttService {
  private client: MqttClient | null = null;
  private connected = false;
  private staleTimer: ReturnType<typeof setInterval> | null = null;
  private lastSeen = new Map<string, number>();
  private lastSteps = new Map<string, { steps: number; timestamp: number }>();

  private onVitalCallbacks: OnVitalData[] = [];
  private onAlertCallbacks: OnAlert[] = [];
  private onAlertRecordCallbacks: OnAlertRecord[] = [];
  private onStatusCallbacks: OnStatusChange[] = [];
  private onCoreTempCallbacks: OnCoreTemp[] = [];

  connect(clientId?: string) {
    if (this.client) return this;
    this.client = mqtt.connect(BROKER_URL, {
      clientId: clientId || `pc-dashboard-${Date.now()}`,
      clean: true,
      connectTimeout: 10_000,
      reconnectPeriod: 5_000,
      username: MQTT_USERNAME || undefined,
      password: MQTT_PASSWORD || undefined,
    });

    this.client.on('connect', () => {
      this.connected = true;
      this.client?.subscribe(Object.values(TOPICS), { qos: 1 }, (error) => {
        if (error) console.error('[MQTT] Subscribe failed:', error.message);
      });
    });
    this.client.on('message', (topic, payload) => this.handleMessage(topic, payload.toString()));
    this.client.on('error', (error) => console.error('[MQTT]', error.message));
    this.client.on('close', () => { this.connected = false; });

    this.staleTimer = setInterval(() => this.expireStaleDevices(), 15_000);
    return this;
  }

  private handleMessage(topic: string, payloadText: string) {
    const parts = topic.split('/');
    if (parts.length !== 3 || parts[0] !== 'watch' || !parts[1]) return;
    const deviceId = parts[1];

    let data: Record<string, unknown>;
    try {
      const parsed = JSON.parse(payloadText);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return;
      data = parsed;
    } catch {
      console.warn('[MQTT] Invalid JSON:', topic);
      return;
    }

    if (topic.endsWith('/vital')) {
      const timestamp = this.validTimestamp(data.timestamp);
      const steps = this.validNumber(data.steps, 0, 10_000_000);
      const vital: VitalData = {
        deviceId,
        timestamp,
        latitude: this.validNumber(data.latitude, -90, 90),
        longitude: this.validNumber(data.longitude, -180, 180),
        gpsAccuracy: this.validNumber(data.gpsAccuracy, 0, 100_000),
        heartRate: this.validNumber(data.heartRate, 30, 250),
        spo2: this.validNumber(data.spo2, 70, 100),
        bloodPressure: this.validBloodPressure(data.bloodPressure),
        coreTemp: this.validNumber(data.coreTemp, 30, 45),
        steps,
        batteryLevel: this.validNumber(data.batteryLevel, 0, 100),
        worn: typeof data.worn === 'boolean' ? data.worn : undefined,
        dataQuality: this.validDataQuality(data.dataQuality),
        firmwareVersion: typeof data.firmwareVersion === 'string' ? data.firmwareVersion : undefined,
      };
      vital.stepRate = this.calculateStepRate(deviceId, steps, timestamp);
      this.markOnline(deviceId);
      this.onVitalCallbacks.forEach((callback) => callback(vital));
      return;
    }

    if (topic.endsWith('/alert')) {
      const alertType = data.alertType === AlertType.HighRisk
        ? AlertType.HighRisk
        : AlertType.Warning;
      const coreTemp = this.validNumber(data.coreTemp, 30, 45);
      const alert: AlertPopupData = {
        deviceId,
        officerName: typeof data.officerName === 'string' && data.officerName.trim()
          ? data.officerName
          : deviceId,
        coreTemp,
        alertType,
        advice: typeof data.advice === 'string' ? data.advice : undefined,
      };
      this.onAlertCallbacks.forEach((callback) => callback(alert));
      const record: AlertRecord = {
        id: `${deviceId}-${String(data.alertId || Date.now())}`,
        timestamp: this.validTimestamp(data.timestamp),
        deviceId,
        officerName: alert.officerName,
        coreTemp,
        alertType,
      };
      this.onAlertRecordCallbacks.forEach((callback) => callback(record));
      return;
    }

    if (topic.endsWith('/status')) {
      const online = data.status === 'online';
      if (online) this.markOnline(deviceId);
      else {
        this.lastSeen.delete(deviceId);
        this.onStatusCallbacks.forEach((callback) => callback(deviceId, false));
      }
      return;
    }

    if (topic.endsWith('/core-temp')) {
      const coreTemp = this.validNumber(data.coreTemperature, 30, 45);
      if (coreTemp == null) return;
      this.onCoreTempCallbacks.forEach((callback) => callback(deviceId, coreTemp));
      return;
    }

  private validTimestamp(value: unknown): number {
    const timestamp = Number(value);
    const min = Date.UTC(2024, 0, 1);
    return Number.isFinite(timestamp) && timestamp >= min && timestamp <= Date.now() + 86_400_000
      ? timestamp
      : Date.now();
  }

  private validNumber(value: unknown, min: number, max: number) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
    return value >= min && value <= max ? value : undefined;
  }

  private validBloodPressure(value: unknown) {
    if (typeof value !== 'string') return undefined;
    const match = /^(\d{2,3})\/(\d{2,3})$/.exec(value);
    if (!match) return undefined;
    const systolic = Number(match[1]);
    const diastolic = Number(match[2]);
    return systolic >= 70 && systolic <= 230 && diastolic >= 40 && diastolic <= 160
      ? value
      : undefined;
  }

  private validDataQuality(value: unknown): VitalData['dataQuality'] {
    return value === 'complete' || value === 'partial' || value === 'not_worn' || value === 'no_vitals'
      ? value
      : undefined;
  }

  private calculateStepRate(deviceId: string, steps: number | undefined, timestamp: number) {
    if (steps == null || steps < 0) return undefined;
    const previous = this.lastSteps.get(deviceId);
    this.lastSteps.set(deviceId, { steps, timestamp });
    if (!previous || steps < previous.steps || timestamp - previous.timestamp < 1_000) return undefined;
    const elapsedMinutes = (timestamp - previous.timestamp) / 60_000;
    return Math.min(300, Math.max(0, (steps - previous.steps) / elapsedMinutes));
  }

  private markOnline(deviceId: string) {
    const wasOnline = this.lastSeen.has(deviceId);
    this.lastSeen.set(deviceId, Date.now());
    if (!wasOnline) this.onStatusCallbacks.forEach((callback) => callback(deviceId, true));
  }

  private expireStaleDevices() {
    const cutoff = Date.now() - OFFLINE_AFTER_MS;
    this.lastSeen.forEach((lastSeen, deviceId) => {
      if (lastSeen < cutoff) {
        this.lastSeen.delete(deviceId);
        this.onStatusCallbacks.forEach((callback) => callback(deviceId, false));
      }
    });
  }

  onVital(callback: OnVitalData) {
    this.onVitalCallbacks.push(callback);
    return () => { this.onVitalCallbacks = this.onVitalCallbacks.filter((item) => item !== callback); };
  }

  onAlert(callback: OnAlert) {
    this.onAlertCallbacks.push(callback);
    return () => { this.onAlertCallbacks = this.onAlertCallbacks.filter((item) => item !== callback); };
  }

  onAlertRecord(callback: OnAlertRecord) {
    this.onAlertRecordCallbacks.push(callback);
    return () => {
      this.onAlertRecordCallbacks = this.onAlertRecordCallbacks.filter((item) => item !== callback);
    };
  }

  onStatus(callback: OnStatusChange) {
    this.onStatusCallbacks.push(callback);
    return () => { this.onStatusCallbacks = this.onStatusCallbacks.filter((item) => item !== callback); };
  }

  onCoreTemp(callback: OnCoreTemp) {
    this.onCoreTempCallbacks.push(callback);
    return () => { this.onCoreTempCallbacks = this.onCoreTempCallbacks.filter((item) => item !== callback); };
  }

  disconnect() {
    if (this.staleTimer) clearInterval(this.staleTimer);
    this.staleTimer = null;
    this.client?.end();
    this.client = null;
    this.connected = false;
    this.lastSeen.clear();
    this.lastSteps.clear();
  }

  isConnected() { return this.connected; }

  publish(topic: string, data: unknown) {
    this.client?.publish(topic, JSON.stringify(data), { qos: 1 });
  }
}

export const mqttService = new MqttService();
