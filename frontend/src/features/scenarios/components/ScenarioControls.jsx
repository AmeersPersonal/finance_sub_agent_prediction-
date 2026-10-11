import { strings } from "../strings.js";
import { formatControlSpeech, formatControlValue } from "../scenarioCalculations.js";
import GlossaryToggletip from "./GlossaryToggletip.jsx";

const CONTROLS = [
  {
    key: "policyRate",
    id: "policy-rate",
    label: strings.policyLabel,
    description: strings.policyDescription,
    learningText: strings.policyLearning,
    glossary: "policyRate",
    min: -1,
    max: 2,
    step: 0.25,
  },
  {
    key: "earningsSurprise",
    id: "earnings-surprise",
    label: strings.earningsLabel,
    description: strings.earningsDescription,
    learningText: strings.earningsLearning,
    glossary: "earningsSurprise",
    min: -30,
    max: 30,
    step: 1,
  },
  {
    key: "sectorDemand",
    id: "sector-demand",
    label: strings.demandLabel,
    description: strings.demandDescription,
    learningText: strings.demandLearning,
    glossary: null,
    min: -25,
    max: 25,
    step: 1,
  },
  {
    key: "cryptoVolatility",
    id: "crypto-volatility",
    label: strings.cryptoLabel,
    description: strings.cryptoDescription,
    learningText: strings.cryptoLearning,
    glossary: "volatility",
    min: 0,
    max: 100,
    step: 5,
  },
];

export default function ScenarioControls({ scenario, onChange, onReset, learning }) {
  return (
    <section id="scenario-controls" className="panel skipTarget" aria-labelledby="controls-heading" tabIndex={-1}>
      <h2 id="controls-heading">{strings.controlsTitle}</h2>
      <p className="lede">{strings.controlsIntro}</p>
      <div className="controlList">
        {CONTROLS.map((control) => (
          <RangeControl
            key={control.key}
            control={control}
            value={scenario[control.key]}
            learning={learning}
            onChange={(value) => onChange(control.key, value)}
          />
        ))}
      </div>
      <button type="button" className="resetButton" onClick={onReset}>
        {strings.resetScenario}
      </button>
    </section>
  );
}

function RangeControl({ control, value, learning, onChange }) {
  const descId = `${control.id}-desc`;
  const learnId = `${control.id}-learn`;
  const describedBy = learning ? `${descId} ${learnId}` : descId;

  return (
    <div className="control">
      <div className="controlLabelRow">
        <label htmlFor={control.id}>{control.label}</label>
        {control.glossary ? <GlossaryToggletip term={control.glossary} /> : null}
        <output htmlFor={control.id} className="numericValue controlValue">
          {formatControlValue(control.key, value)}
        </output>
      </div>
      <p id={descId} className="helpText">
        {control.description}
      </p>
      <input
        id={control.id}
        className="range"
        type="range"
        min={control.min}
        max={control.max}
        step={control.step}
        value={value}
        aria-describedby={describedBy}
        aria-valuetext={formatControlSpeech(control.key, value)}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {learning ? (
        <p id={learnId} className="learningNote">
          {control.learningText}
        </p>
      ) : null}
    </div>
  );
}
