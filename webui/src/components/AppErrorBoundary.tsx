import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("E-ink Map Tiles failed to render", error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <main className="fatal-error">
        <h1>E-ink Map Tiles could not continue</h1>
        <p>{this.state.error.message}</p>
        <button onClick={() => window.location.reload()}>Reload application</button>
      </main>
    );
  }
}
