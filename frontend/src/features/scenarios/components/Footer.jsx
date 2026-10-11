import { strings } from "../strings.js";

export default function Footer() {
  return (
    <footer className="siteFooter">
      <p>
        {strings.productName}
        <span aria-hidden="true"> · </span>
        {strings.pageTitle}
      </p>
      <p className="disclaimer">{strings.disclaimer}</p>
    </footer>
  );
}
