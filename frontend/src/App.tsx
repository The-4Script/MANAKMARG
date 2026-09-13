import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";

const Navigator = lazy(() => import("./pages/Navigator"));
const Assistant = lazy(() => import("./pages/Assistant"));
const Journey = lazy(() => import("./pages/Journey"));
const Standards = lazy(() => import("./pages/Standards"));
const Certification = lazy(() => import("./pages/Certification"));
const Labs = lazy(() => import("./pages/Labs"));
const Hallmarking = lazy(() => import("./pages/Hallmarking"));
const GapAnalysis = lazy(() => import("./pages/GapAnalysis"));
const Sources = lazy(() => import("./pages/Sources"));

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/" element={<Navigator />} />
          <Route path="/assistant" element={<Assistant />} />
          <Route path="/journey" element={<Journey />} />
          <Route path="/standards" element={<Standards />} />
          <Route path="/standards/:stdKey" element={<Standards />} />
          <Route path="/certification" element={<Certification />} />
          <Route path="/labs" element={<Labs />} />
          <Route path="/hallmarking" element={<Hallmarking />} />
          <Route path="/gap-analysis" element={<GapAnalysis />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="*" element={<Navigator />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
