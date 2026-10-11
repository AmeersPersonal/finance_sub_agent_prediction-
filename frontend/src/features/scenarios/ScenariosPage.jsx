import { useEffect, useMemo, useRef, useState } from "react";
import "./scenarios.css";
import { strings } from "./strings.js";
import { DEFAULT_SCENARIO } from "./scenarioData.js";
import { buildAnnouncement, buildInterpretation, calculateScenario } from "./scenarioCalculations.js";
import { useTheme } from "./useTheme.js";
import AccessibilityNotes from "./components/AccessibilityNotes.jsx";
import Footer from "./components/Footer.jsx";
import HypotheticalBanner from "./components/HypotheticalBanner.jsx";
import ScenarioChart from "./components/ScenarioChart.jsx";
import ScenarioControls from "./components/ScenarioControls.jsx";
import ScenarioHeader from "./components/ScenarioHeader.jsx";
import ScenarioInterpretation from "./components/ScenarioInterpretation.jsx";
import ScenarioResultsTable from "./components/ScenarioResultsTable.jsx";
import SkipLinks from "./components/SkipLinks.jsx";
import WhatThisDoesNotTellYou from "./components/WhatThisDoesNotTellYou.jsx";

export default function ScenariosPage() {
  const [theme, setTheme] = useTheme();
  const [learning, setLearning] = useState(false);
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [tableView, setTableView] = useState(false);
  const [notice, setNotice] = useState("update");
  const headingRef = useRef(null);
  const learningRef = useRef(null);

  const results = useMemo(() => calculateScenario(scenario), [scenario]);
  const interpretation = useMemo(() => buildInterpretation(scenario), [scenario]);
  const pendingMessage = useMemo(
    () => buildAnnouncement(results, { reset: notice === "reset" }),
    [results, notice],
  );
  const announcement = useDebouncedMessage(pendingMessage);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = strings.documentTitle;
    headingRef.current?.focus();
    return () => {
      document.title = previousTitle;
    };
  }, []);

  function updateControl(key, value) {
    setNotice("update");
    setScenario((current) => ({ ...current, [key]: value }));
  }

  function resetScenario() {
    setNotice("reset");
    setScenario(DEFAULT_SCENARIO);
  }

  return (
    <div className="mms" data-theme={theme}>
      <SkipLinks />
      <ScenarioHeader
        theme={theme}
        setTheme={setTheme}
        learning={learning}
        setLearning={setLearning}
        learningRef={learningRef}
        headingRef={headingRef}
        onOpenSettings={() => learningRef.current?.focus()}
      />
      <main className="pageMain" id="main">
        <HypotheticalBanner />
        <div className="pageGrid">
          <ScenarioControls scenario={scenario} onChange={updateControl} onReset={resetScenario} learning={learning} />
          <section id="scenario-results" className="panel resultsPanel skipTarget" aria-labelledby="results-heading" tabIndex={-1}>
            <div className="resultsHead">
              <div>
                <h2 id="results-heading">{strings.resultsTitle}</h2>
                <p className="lede">{strings.resultsIntro}</p>
              </div>
              <button
                type="button"
                className="textButton"
                aria-pressed={tableView}
                onClick={() => setTableView((value) => !value)}
              >
                {tableView ? strings.viewAsChart : strings.viewAsTable}
              </button>
            </div>
            {tableView ? (
              <ScenarioResultsTable results={results} learning={learning} />
            ) : (
              <ScenarioChart results={results} learning={learning} />
            )}
            <p className="disclaimer" role="note">
              {strings.disclaimer}
            </p>
          </section>
        </div>
        <ScenarioInterpretation text={interpretation} learning={learning} />
        <WhatThisDoesNotTellYou />
        <AccessibilityNotes />
      </main>
      <Footer />
      <div className="visuallyHidden" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
    </div>
  );
}

function useDebouncedMessage(message) {
  const [announced, setAnnounced] = useState("");
  const initial = useRef(message);
  const seenChange = useRef(false);

  useEffect(() => {
    if (!seenChange.current) {
      if (message === initial.current) return undefined;
      seenChange.current = true;
    }
    const timer = window.setTimeout(() => setAnnounced(message), 500);
    return () => window.clearTimeout(timer);
  }, [message]);

  return announced;
}
