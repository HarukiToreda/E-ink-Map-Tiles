import type { TileDepth } from "../models";
import type { PixelBuffer } from "./eink";
import type { ConversionRequest, ConversionResponse } from "./workerProtocol";

export class ConversionWorkerClient {
  private worker = new Worker(new URL("./render.worker.ts", import.meta.url), { type: "module" });
  private failure: Error | null = null;
  private waiting = new Map<
    string,
    { resolve: (value: Uint8Array) => void; reject: (error: Error) => void }
  >();

  constructor() {
    this.worker.onmessage = (event: MessageEvent<ConversionResponse>) => {
      const pending = this.waiting.get(event.data.id);
      if (!pending) return;
      this.waiting.delete(event.data.id);
      if (event.data.type === "error") pending.reject(new Error(event.data.error));
      else pending.resolve(new Uint8Array(event.data.result));
    };
    this.worker.onerror = (event) => {
      this.fail(new Error(event.message || "Conversion worker failed"));
    };
    this.worker.onmessageerror = () => this.fail(new Error("Conversion worker response failed"));
  }

  private rejectAll(error: Error) {
    this.waiting.forEach(({ reject }) => reject(error));
    this.waiting.clear();
  }

  private fail(error: Error) {
    this.failure = error;
    this.worker.terminate();
    this.rejectAll(error);
  }

  convert(source: PixelBuffer, depth: TileDepth, pack: boolean): Promise<Uint8Array> {
    if (this.failure) return Promise.reject(this.failure);
    const id = crypto.randomUUID(),
      rgba = source.data.slice().buffer;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject });
      const request: ConversionRequest = {
        id,
        rgba,
        width: source.width,
        height: source.height,
        depth,
        pack,
      };
      this.worker.postMessage(request, [rgba]);
    });
  }

  destroy() {
    this.fail(this.failure ?? new Error("Conversion cancelled"));
  }
}
