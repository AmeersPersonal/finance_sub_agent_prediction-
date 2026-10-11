import { useEffect, useState } from "react";
import { strings } from "../strings.js";
import {
  directionSymbol,
  directionWord,
  formatLevel,
  formatSignedPoints,
  illustrativePhrase,
} from "../scenarioCalculations.js";
import GlossaryToggletip from "./GlossaryToggletip.jsx";

export default function ScenarioResultsTable({ results, learning }) {
  const stacked = useMediaQuery("(max-width: 767px)");
  if (stacked) return <StackedResults results={results} learning={learning} />;
  return <WideTable results={results} learning={learning} />;
}

function WideTable({ results, learning }) {
  return (
    <div className="tableWrap">
      <table className="scenarioTable">
        <caption>{strings.tableCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{strings.colAsset}</th>
            <th scope="col">{strings.colType}</th>
            <th scope="col">{strings.colStart}</th>
            <th scope="col">{strings.colChange}</th>
            <th scope="col">{strings.colDirection}</th>
            <th scope="col">{strings.colExplanation}</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => (
            <tr key={result.symbol}>
              <th scope="row">
                <span className="resultSymbol">{result.symbol}</span>
                <span className="resultName">{result.name}</span>
              </th>
              <td>
                <TypeCell result={result} />
              </td>
              <td>
                <span className="priceValue">{formatLevel(result.startingValue)}</span>
              </td>
              <td>
                <span className={`scenarioChange is-${result.direction}`}>{illustrativePhrase(result)}</span>
              </td>
              <td>
                <DirectionCell result={result} />
              </td>
              <td>
                <ExplanationCell result={result} learning={learning} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StackedResults({ results, learning }) {
  return (
    <div className="stackList">
      <p className="tableCaption">{strings.tableCaption}</p>
      {results.map((result) => (
        <article key={result.symbol} className="stackCard" aria-labelledby={`asset-${result.symbol}`}>
          <h3 id={`asset-${result.symbol}`}>
            <span className="resultSymbol">{result.symbol}</span>
            <span className="resultName">{result.name}</span>
          </h3>
          <dl className="stackFields">
            <div>
              <dt>{strings.colType}</dt>
              <dd>
                <TypeCell result={result} />
              </dd>
            </div>
            <div>
              <dt>{strings.colStart}</dt>
              <dd>
                <span className="priceValue">{formatLevel(result.startingValue)}</span>
              </dd>
            </div>
            <div>
              <dt>{strings.colChange}</dt>
              <dd>
                <span className={`scenarioChange is-${result.direction}`}>{illustrativePhrase(result)}</span>
              </dd>
            </div>
            <div>
              <dt>{strings.colDirection}</dt>
              <dd>
                <DirectionCell result={result} />
              </dd>
            </div>
            <div>
              <dt>{strings.colExplanation}</dt>
              <dd>
                <ExplanationCell result={result} learning={learning} />
              </dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function TypeCell({ result }) {
  if (result.type === "Index fund") {
    return <GlossaryToggletip term="indexFund" />;
  }
  return <span className="resultType">{result.type}</span>;
}

function DirectionCell({ result }) {
  return (
    <span className={`numericValue is-${result.direction}`}>
      {directionSymbol(result.direction)} {directionWord(result.direction)} {formatSignedPoints(result.signedValue)}
    </span>
  );
}

function ExplanationCell({ result, learning }) {
  return (
    <>
      <span className="explanation">{result.explanation}</span>
      {learning ? <span className="learningNote">{strings.assetLearning[result.symbol]}</span> : null}
    </>
  );
}

function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const media = window.matchMedia(query);
    const listener = () => setMatches(media.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [query]);

  return matches;
}
