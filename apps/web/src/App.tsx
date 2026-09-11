import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AboutPage } from "./pages/AboutPage";
import { AdminPublicationPage } from "./pages/AdminPublicationPage";
import { CourseCenterPage } from "./pages/CourseCenterPage";
import { CourseSettingsPage } from "./pages/CourseSettingsPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { QaPage } from "./pages/QaPage";
import { TasksPage } from "./pages/TasksPage";
import { LearningPage } from "./pages/LearningPage";
import { v3Enabled } from "./services/learningApi";


export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route element={<HomePage />} index />
        <Route element={<AboutPage />} path="about" />
        <Route element={<ProtectedRoute />}>
          {v3Enabled && <Route element={<LearningPage />} path="learn/:courseId" />}
          <Route element={<QaPage />} path="qa" />
          <Route element={<QaPage />} path="qa/:courseId" />
          <Route element={<QaPage />} path="qa/:courseId/:conversationId" />
          <Route element={<CourseCenterPage />} path="courses" />
          <Route element={<CourseCenterPage createMode />} path="courses/new" />
          <Route element={<CourseSettingsPage />} path="courses/:courseId/settings" />
          <Route element={<AdminPublicationPage />} path="admin/publications" />
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
