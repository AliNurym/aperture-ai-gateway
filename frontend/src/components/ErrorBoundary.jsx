import { Component } from "react";

export default class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <main
          className="console-panel"
          style={{ maxWidth: 520, margin: "15vh auto", padding: 32 }}
          role="alert"
        >
          <h1 style={{ fontSize: 24, marginBottom: 14 }}>
            The workspace hit a snag.
          </h1>
          <p style={{ lineHeight: 1.7, marginBottom: 22 }}>
            Reload to open the workspace again. If a gateway task was running,
            check its status before submitting it again.
          </p>
          <button
            className="console-button primary"
            onClick={() => window.location.reload()}
          >
            Reload workspace
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
