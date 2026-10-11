import { strings } from "../strings.js";

export default function ConnectionStatus() {
  return (
    <p className="status" role="status">
      <span className="statusMark" aria-hidden="true" />
      <span>{strings.status}</span>
      <span className="statusDetail">{strings.statusDetail}</span>
    </p>
  );
}
