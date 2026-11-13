export interface Station { id: string; name: string; area: string; lat: number; lng: number; x: number; y: number; zone: string; line_ids: string[] }
export interface Line { id: string; name: string; color: string; operator_id: string; station_ids: string[]; family_id?: string; segments?: {seconds: number; metres: number; zone: string}[] }
export interface Network { stations: Station[]; lines: Line[]; configured: boolean; version: string; provider: string | null; source_url: string | null; simulated: boolean; journey_planning?: boolean; coverage_note?: string; published_at?: string; sources?: {url: string; scope: string}[]; operators: { id: string; name: string; website: string; map_url: string }[] }
export interface Arrival {
  id: string; trip_id: string; train_code: string; station_id: string; line_id: string; direction: string;
  towards: string; platform: string | null; arrival_at: string; scheduled_arrival_at?: string; remaining_seconds: number; delay_seconds: number;
  source: string; context: string; trust_score: number; freshness_status: string; last_observation_at: string | null;
  generated_at: string; version: number; model_version: string;
}
export interface Alert { id: string; title: string; line_id: string; delay_seconds: number; source: string; freshness_status: string }
export interface Snapshot { station_id: string; arrivals: Arrival[]; generated_at: string; snapshot_version: number; alerts: Alert[] }
export interface TripState {
  context: string; source: string; trust: number; position_m: number; accepted_position_m: number;
  speed_mps: number | null; reason: string; scores: Record<string, number>; last_observed_at: string | null;
  transition: { deadline: string; started_at: string } | null;
  backend_mode?: string;
  arbitration?: { estimated_trust: number; incoming_trust: Record<string, number>; winner: string | null; reason: string } | null;
}
export interface Trip { id: string; code: string; line_id: string; direction: string; state: TripState; version: number }
export interface Decision { at: string; source: string; reason: string; scores: Record<string, number> }
export interface SourceStatus extends TripState { trip_id: string; decisions: Decision[] }
export interface RouteStep {
  kind: string; from_station_id: string; to_station_id: string; line_id: string; seconds: number;
  wait_seconds: number; departure_at: string; arrival_at: string; source: string;
  requires_exit?: boolean;
  family_id?: string; context?: string; walking_metres?: number; delay_seconds?: number; last_observed_at?: string | null;
  source_status?: JourneySourceStatus | null;
}
export type Preference = 'fastest' | 'fewest_changes' | 'least_walking' | 'shortest_distance';
export interface Route { id: string; duration_seconds: number; transfers: number; source: string; steps: RouteStep[]; arrival_at: string; walking_metres?: number; distance_metres?: number; station_count?: number; recommendations?: Preference[]; delay_seconds?: number; source_statuses?: JourneySourceStatus[] }
export interface JourneySourceStatus {
  source: string; scope: 'static' | 'identified_train' | 'station_service'; planned_context: string; train_context: string | null;
  preferred_source: string; trust_score: number | null; freshness_status: string; last_observed_at: string | null;
  age_seconds: number | null; valid_until: string | null; reason: string; model_version: string;
  next_arrival: Arrival | null; transition: TripState['transition']; arbitration: TripState['arbitration'];
  boarding_station_id?: string; line_id?: string; direction?: string; delay_seconds: number;
}
export interface JourneySnapshot { origin: string; destination: string; preference: Preference; network_version?: string; routes: Route[]; reason: string | null; generated_at: string; snapshot_version: number; timing_note?: string; rerouting?: {status: string; saving_seconds: number; baseline_route_id?: string; suggested_route_id?: string; valid_until?: string | null} }
export interface CommunitySignal { event_type?: string; station_id: string; line_id: string; direction: string; status: string; source: string; confirmations: number; required_confirmations: number; delay_seconds: number | null; last_observed_at: string; age_seconds: number; trust_score: number; expires_at?: string }
export interface SurfaceReport { event_type?: string; event_id: string; station_id: string; line_id: string; direction: string; observed_at: string; latitude: number; longitude: number; accuracy_m: number; delay_seconds: number; note: string }
export interface ReportOutcome { event_type?: string; live_ttl_seconds?: number; validated_at?: string; event_id: string; station_id: string; line_id: string; direction: string; delay_seconds: number; observed_at: string; received_at: string; age_seconds: number; processing_status: string; outcome: string; reason: string; confirmations: number; required_confirmations: number }
export interface Report {
  event_id: string; trip_id: string; contributor_id: string; direction: string; observed_at: string;
  accuracy_m: number; latitude: number; longitude: number; kind: string; note: string;
}
export interface Acknowledgement { event_id: string; status: string; reason?: string; client_event_id?: string; index: number }
