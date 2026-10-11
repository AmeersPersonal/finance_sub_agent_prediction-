import { strings } from "../strings.js";

export default function SkipLinks() {
  return (
    <>
      <a className="skip" href="#scenario-controls">
        {strings.skipToControls}
      </a>
      <a className="skip" href="#scenario-results">
        {strings.skipToResults}
      </a>
    </>
  );
}
