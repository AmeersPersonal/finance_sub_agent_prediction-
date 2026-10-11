import { strings } from "../strings.js";

const NOTES = [strings.notesKeyboard, strings.notesPatterns, strings.notesChart, strings.notesAudit];

export default function AccessibilityNotes() {
  return (
    <section className="notes" aria-labelledby="accessibility-heading">
      <h2 id="accessibility-heading">{strings.accessibilityTitle}</h2>
      <ol className="noteList">
        {NOTES.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ol>
    </section>
  );
}
