import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("React ErrorBoundary caught an error:", error, errorInfo);
    this.setState({ errorInfo });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '40px', color: '#f87171', background: '#0c0926', minHeight: '100vh', fontFamily: 'monospace' }}>
          <h2>⚠️ Finplus PnL App Encountered a Component Render Error</h2>
          <pre style={{ background: '#1c1646', padding: '20px', borderRadius: '8px', color: '#fbbf24', marginTop: '20px', overflowX: 'auto' }}>
            {this.state.error && this.state.error.toString()}
          </pre>
          <pre style={{ background: '#151036', padding: '20px', borderRadius: '8px', color: '#a5b4fc', marginTop: '20px', overflowX: 'auto' }}>
            {this.state.errorInfo && this.state.errorInfo.componentStack}
          </pre>
          <button 
            onClick={() => {
              window.location.reload();
            }}
            style={{ marginTop: '20px', padding: '12px 24px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}
          >
            Reload Application
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
