import type { ReactNode } from "react";

import "./DashboardQuickActions.css";

type DashboardQuickActionsProps = {
  ariaLabel: string;
  importCanvasLabel: string;
  createCourseLabel: string;
  viewAllCoursesLabel: string;
  importCanvasIcon?: ReactNode;
  createCourseIcon?: ReactNode;
  onImportCanvas: () => void;
  onCreateCourse: () => void;
  onViewAllCourses: () => void;
};

function CourseGridIcon() {
  return (
    <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1" />
      <rect x="14" y="3.5" width="6.5" height="6.5" rx="1" />
      <rect x="3.5" y="14" width="6.5" height="6.5" rx="1" />
      <rect x="14" y="14" width="6.5" height="6.5" rx="1" />
    </svg>
  );
}

export function DashboardQuickActions({
  ariaLabel,
  importCanvasLabel,
  createCourseLabel,
  viewAllCoursesLabel,
  importCanvasIcon,
  createCourseIcon,
  onImportCanvas,
  onCreateCourse,
  onViewAllCourses,
}: DashboardQuickActionsProps) {
  const actions = [
    { key: "canvas", label: importCanvasLabel, icon: importCanvasIcon, onClick: onImportCanvas },
    { key: "course", label: createCourseLabel, icon: createCourseIcon, onClick: onCreateCourse },
    { key: "all", label: viewAllCoursesLabel, icon: <CourseGridIcon />, onClick: onViewAllCourses },
  ];

  return (
    <div className="cj-dashboard-actions" role="group" aria-label={ariaLabel}>
      {actions.map((action) => (
        <button key={action.key} type="button" className="cj-dashboard-action" onClick={action.onClick}>
          <span className="cj-dashboard-action-icon">{action.icon}</span>
          <span className="cj-dashboard-action-label">{action.label}</span>
        </button>
      ))}
    </div>
  );
}
