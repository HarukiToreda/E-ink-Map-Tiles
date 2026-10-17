import { planTileCoverage } from "./tiles";
import type { TilePlanRequest, TilePlanResponse } from "./workerProtocol";

self.onmessage = (event: MessageEvent<TilePlanRequest>) => {
  try {
    const response: TilePlanResponse = {
      type: "result",
      tiles: planTileCoverage(event.data).tiles,
    };
    self.postMessage(response);
  } catch (error) {
    const response: TilePlanResponse = {
      type: "error",
      error: error instanceof Error ? error.message : String(error),
    };
    self.postMessage(response);
  }
};
