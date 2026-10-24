import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";

import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

class RenderGuard extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, details: ErrorInfo) {
    console.error("Dashboard render failed", error, details);
  }

  render() {
    if (this.state.failed) return <div className="app-shell">
      <div className="page">
        <main id="main-content" className="empty-state" role="alert">
          <h1>The live console was interrupted</h1>
          <p>Your run is still safe. Reload to reconnect to its event stream.</p>
          <a className="source-link" href={window.location.href}>Reload console</a>
        </main>
      </div>
    </div>;
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RenderGuard><App /></RenderGuard>
  </StrictMode>,
);
