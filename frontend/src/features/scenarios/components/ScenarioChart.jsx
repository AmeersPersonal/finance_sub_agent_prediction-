import { strings } from "../strings.js";
import {
  buildChartLabel,
  directionSymbol,
  directionWord,
  formatLevel,
  formatSignedPercent,
  formatSignedPoints,
  illustrativePhrase,
} from "../scenarioCalculations.js";
import GlossaryToggletip from "./GlossaryToggletip.jsx";

export default function ScenarioChart({ results, learning }) {
  const maxAbs = Math.max(2, ...results.map((result) => Math.abs(result.changePercent)));
  const scale = maxAbs * 1.15;

  return (
    <div className="chartBlock">
      <div className="chartSurface" role="img" tabIndex={0} aria-label={buildChartLabel(results)}>
        <div className="chartRows" aria-hidden="true">
          {results.map((result) => (
            <ChartRow key={result.symbol} result={result} scale={scale} />
          ))}
        </div>
      </div>
      <ul className="legend" aria-label={strings.legendLabel}>
        <li>
          <span className="is-up" aria-hidden="true">
            {strings.symbolUp}
          </span>
          {strings.directionUp}
        </li>
        <li>
          <span className="is-down" aria-hidden="true">
            {strings.symbolDown}
          </span>
          {strings.directionDown}
        </li>
        <li>
          <span className="is-neutral" aria-hidden="true">
            {strings.symbolNeutral}
          </span>
          {strings.directionNeutral}
        </li>
      </ul>
      <p className="helpText">{strings.chartNote}</p>
      {learning ? <p className="learningNote">{strings.interpretationLearning}</p> : null}
      <ul className="resultList">
        {results.map((result) => (
          <li key={result.symbol} className="resultItem">
            <div className="resultIdentity">
              <span className="resultSymbol">{result.symbol}</span>
              <span className="resultName">{result.name}</span>
              <span className="resultType">
                {result.type === "Index fund" ? <GlossaryToggletip term="indexFund" /> : result.type}
              </span>
            </div>
            <p className="resultFigure">
              <span className="metaLabel">{strings.exampleStartingValue}</span>
              <span className="priceValue">{formatLevel(result.startingValue)}</span>
            </p>
            <p className={`scenarioChange is-${result.direction}`}>{illustrativePhrase(result)}</p>
            <p className="resultFigure">
              <span className="metaLabel">{strings.signedValueLabel}</span>
              <span className={`numericValue is-${result.direction}`}>
                {directionSymbol(result.direction)} {formatSignedPoints(result.signedValue)}
              </span>
            </p>
            <p className="explanation">{result.explanation}</p>
            {learning ? <p className="learningNote">{strings.assetLearning[result.symbol]}</p> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChartRow({ result, scale }) {
  const normalized = result.changePercent / scale;
  const magnitude = Math.min(Math.abs(normalized), 1) * 50;
  const width = Math.max(magnitude, result.direction === "neutral" ? 0.8 : 1.2);
  const x = normalized >= 0 ? 0 : -width;

  return (
    <div className="chartRow">
      <span className="chartSymbol">{result.symbol}</span>
      <svg className="barSvg" viewBox="-50 -10 100 20" preserveAspectRatio="none" role="presentation">
        <line className="axisLine" x1="-50" x2="50" y1="0" y2="0" />
        <line className="zeroLine" x1="0" x2="0" y1="-10" y2="10" />
        <rect className={`chartBar is-${result.direction}`} x={x} y="-6" width={width} height="12" />
      </svg>
      <span className={`chartValue scenarioChange is-${result.direction}`}>
        {directionSymbol(result.direction)} {formatSignedPercent(result.changePercent)} {directionWord(result.direction)}
      </span>
    </div>
  );
}
