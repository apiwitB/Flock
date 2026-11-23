// รูปแบบข้อมูลตาม response model ใน api/flock_api/app.py

export type Role = "viewer" | "investigator" | "admin";

export interface User {
  username: string;
  role: string;
}

export interface AttributeValue {
  value: string;
  confidence?: number | null;
}

export type LinkMethod = "new" | "exact" | "similar_plate" | "guess";
export type MatchKind = "exact" | "similar" | "partial";

export interface Sighting {
  sighting_id: string;
  observed_at: string;
  camera_id: string;
  subject_type: string;
  local_track_id: string;
  plate_text: string | null;
  plate_confidence: number | null;
  province: string | null;
  province_confidence: number | null;
  attributes: Record<string, unknown>;
  journey_id: number | null;
  link_method: string | null;
  link_score: number | null;
  crop_url: string;
  context_url: string;
}

export interface PlateMatch extends Sighting {
  match: MatchKind;
  distance: number;
}

export interface Journey {
  journey_id: number;
  subject_type: string;
  first_seen: string;
  last_seen: string;
  plate_text: string | null;
  province: string | null;
  plate_confidence: number | null;
  closed: boolean;
  weakest_link: "exact" | "similar_plate" | "guess" | null;
  sightings: Sighting[];
}

export interface Camera {
  camera_id: string;
  name: string | null;
  location: string | null;
}

export interface PlateSearchParams {
  q: string;
  from: string;
  to: string;
  camera_id?: string | undefined;
  province?: string | undefined;
  max_distance?: number | undefined;
  limit?: number | undefined;
}

export interface BrowseParams {
  from: string;
  to: string;
  camera_id?: string | undefined;
  color?: string | undefined;
  vehicle_type?: string | undefined;
  limit?: number | undefined;
}
