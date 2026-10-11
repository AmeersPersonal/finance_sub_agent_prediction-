import { Link } from "react-router-dom";
import { strings } from "../strings.js";
import ConnectionStatus from "./ConnectionStatus.jsx";
import DashboardLink from "./DashboardLink.jsx";
import LearningToggle from "./LearningToggle.jsx";
import ThemeToggle from "./ThemeToggle.jsx";
import UserMenu from "./UserMenu.jsx";

export default function ScenarioHeader({
  theme,
  setTheme,
  learning,
  setLearning,
  learningRef,
  headingRef,
  onOpenSettings,
}) {
  return (
    <header className="siteHeader">
      <div className="headerBrand">
        <p className="productName">{strings.productName}</p>
        <h1 id="page-title" ref={headingRef} tabIndex={-1}>
          {strings.pageTitle}
        </h1>
        <nav aria-label={strings.breadcrumbNavLabel}>
          <ol className="breadcrumb">
            <li>
              <Link to="/Dashboard" state={{ fromScenarios: true }}>
                {strings.dashboardCrumb}
              </Link>
            </li>
            <li aria-current="page">{strings.scenariosCrumb}</li>
          </ol>
        </nav>
      </div>
      <div className="headerTools">
        <DashboardLink />
        <LearningToggle learning={learning} setLearning={setLearning} buttonRef={learningRef} />
        <ThemeToggle theme={theme} setTheme={setTheme} />
        <ConnectionStatus />
        <UserMenu onOpenSettings={onOpenSettings} />
      </div>
    </header>
  );
}
