import { planTileCoverage } from "./tiles";
import type { EstimateRequest, EstimateResponse } from "./workerProtocol";

self.onmessage = (event: MessageEvent<EstimateRequest>) => {
  try {
    const result = planTileCoverage(
      event.data.session,
      (progress) => {
        const response: EstimateResponse = { type: "progress", progress };
        self.postMessage(response);
      },
      event.data.cached,
    );
    const response: EstimateResponse = {
      type: "result",
      tiles: result.tiles,
      cacheWrites: result.cacheWrites,
    };
    self.postMessage(response);
  } catch (error) {
    const response: EstimateResponse = {
      type: "error",
      error: error instanceof Error ? error.message : String(error),
    };
    self.postMessage(response);
  }
};
