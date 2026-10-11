import { Link } from "react-router-dom";
import { strings } from "../strings.js";

// The Market Move Dashboard in this app is served at /Dashboard.
export default function DashboardLink() {
  return (
    <Link className="textButton" to="/Dashboard" state={{ fromScenarios: true }}>
      {strings.backToDashboard}
    </Link>
  );
}
