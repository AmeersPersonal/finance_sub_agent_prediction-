import { strings } from "../strings.js";

const ITEMS = [strings.notForecastItem, strings.notEveryFactor, strings.notADecision];

export default function WhatThisDoesNotTellYou() {
  return (
    <section className="panel limits" aria-labelledby="limits-heading">
      <h2 id="limits-heading">{strings.whatThisDoesNotTellYou}</h2>
      <ul className="limitList">
        {ITEMS.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
