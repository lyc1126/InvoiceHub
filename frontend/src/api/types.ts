// Subsets of /api/v1 payloads consumed by the workspace shell. Field names follow
// AppState.health() and AppState.settings(); extend here before using a new field.
export interface HealthPayload {
  ok: boolean;
  product_version: string;
  platform: string;
  background_status: string;
  watch_dir: string;
  target_id: string;
}

export interface SettingsPayload {
  ok: boolean;
  watch_dir: string;
  active_target_id: string;
}
