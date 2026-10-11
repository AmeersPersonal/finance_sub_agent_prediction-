import { strings } from "../strings.js";

export default function LearningToggle({ learning, setLearning, buttonRef }) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className="textButton"
      aria-pressed={learning}
      onClick={() => setLearning((value) => !value)}
    >
      <span>{strings.learningMode}</span>
      <span className="toggleState">{learning ? strings.learningOn : strings.learningOff}</span>
    </button>
  );
}
