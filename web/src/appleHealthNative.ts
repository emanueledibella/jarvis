import { Capacitor } from "@capacitor/core";
import { nativePlugin } from "./remoteClient";

export const healthMetrics = ["steps", "sleep_minutes", "heart_rate", "resting_heart_rate", "active_energy", "distance", "workout_minutes"] as const;
export type HealthMetric = typeof healthMetrics[number];
export interface HealthSnapshot {
  version: 1;
  first_date: string;
  last_date: string;
  timezone: string;
  collected_at: string;
  metrics: HealthMetric[];
  records_scanned: number;
  rows: { date: string; metric: HealthMetric; source: string; source_id: string; unit: string; aggregation: string; value: number; min: number; max: number; count: number }[];
}

export const iosHealth = {
  supported: () => Capacitor.isNativePlatform() && Capacitor.getPlatform() === "ios",
  available: async () => (await nativePlugin.healthStatus()).available,
  read: (metrics: HealthMetric[], days: number) => nativePlugin.healthRead({ metrics, days }),
  cancel: () => nativePlugin.healthCancel(),
};
