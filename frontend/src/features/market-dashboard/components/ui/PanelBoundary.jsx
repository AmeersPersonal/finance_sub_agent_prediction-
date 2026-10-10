// Error boundary so one crashing panel doesn't take down the whole dashboard.
import { Component } from 'react';
import { strings } from '../../constants/strings.js';

export default class PanelBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    // Visible in the browser console while debugging.
    console.error(`[${this.props.title}] panel crashed:`, error, info);
  }

  render() {
    if (this.state.failed) {
      return (
        <div role="alert" className="panel">
          {this.props.title}: {strings.error}
          <button className="action ml-3" onClick={() => this.setState({ failed: false })}>{strings.retry}</button>
        </div>
      );
    }
    return this.props.children;
  }
}
