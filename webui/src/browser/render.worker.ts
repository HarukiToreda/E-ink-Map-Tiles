import { convertToMtbPixels, packMtbColumnMajor } from "./eink";
import type { ConversionRequest, ConversionResponse } from "./workerProtocol";

self.onmessage = (event: MessageEvent<ConversionRequest>) => {
  const request = event.data;
  try {
    const pixels = convertToMtbPixels(
      {
        width: request.width,
        height: request.height,
        data: new Uint8ClampedArray(request.rgba),
      },
      request.depth,
    );
    const result = request.pack
      ? packMtbColumnMajor(pixels, request.depth, request.width, request.height)
      : pixels;
    const response: ConversionResponse = {
      type: "result",
      id: request.id,
      result: result.buffer,
    };
    self.postMessage(response, { transfer: [result.buffer] });
  } catch (error) {
    const response: ConversionResponse = {
      type: "error",
      id: request.id,
      error: error instanceof Error ? error.message : String(error),
    };
    self.postMessage(response);
  }
};
