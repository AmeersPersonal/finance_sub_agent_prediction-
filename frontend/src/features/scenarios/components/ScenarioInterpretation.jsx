import { strings } from "../strings.js";

export default function ScenarioInterpretation({ text, learning }) {
  return (
    <section className="panel" aria-labelledby="interpretation-heading">
      <h2 id="interpretation-heading">{strings.interpretationTitle}</h2>
      <p className="interpretation">{text}</p>
      {learning ? <p className="learningNote">{strings.interpretationLearning}</p> : null}
    </section>
  );
}
