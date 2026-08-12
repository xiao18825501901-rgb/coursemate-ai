import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AboutPage } from "./pages/AboutPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { QaPage } from "./pages/QaPage";
import { TasksPage } from "./pages/TasksPage";


export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route element={<HomePage />} index />
        <Route element={<AboutPage />} path="about" />
        <Route element={<ProtectedRoute />}>
          <Route element={<QaPage />} path="qa" />
          <Route element={<QaPage />} path="qa/:courseId" />
          <Route element={<TasksPage />} path="tasks" />
          <Route element={<DocumentsPage />} path="documents" />
        </Route>
        <Route element={<NotFoundPage />} path="*" />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </ErrorBoundary>
  );
}
