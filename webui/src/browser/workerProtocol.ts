import type { TileDepth } from "../models";
import type {
  TileCoordinate,
  TileCoverageSession,
  TileEstimateProgress,
  TilePlanCacheEntry,
} from "./tiles";

export interface ConversionRequest {
  id: string;
  rgba: ArrayBuffer;
  width: number;
  height: number;
  depth: TileDepth;
  pack: boolean;
}

export type ConversionResponse =
  | { type: "result"; id: string; result: ArrayBuffer }
  | { type: "error"; id: string; error: string };

export interface EstimateRequest {
  session: TileCoverageSession;
  cached: Record<string, TileCoordinate[]>;
}

export type EstimateResponse =
  | { type: "progress"; progress: TileEstimateProgress }
  | { type: "result"; tiles: TileCoordinate[]; cacheWrites: TilePlanCacheEntry[] }
  | { type: "error"; error: string };

export type TilePlanRequest = TileCoverageSession;

export type TilePlanResponse =
  { type: "result"; tiles: TileCoordinate[] } | { type: "error"; error: string };
