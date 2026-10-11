import { lazy, Suspense } from "react";
import { strings } from "../features/scenarios/strings.js";

const ScenariosPage = lazy(() => import("../features/scenarios/ScenariosPage.jsx"));

export default function Scenarios() {
  return (
    <Suspense fallback={<p>{strings.loading}</p>}>
      <ScenariosPage />
    </Suspense>
  );
}
