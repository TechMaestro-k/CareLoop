import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { PatientShell } from "@/components/layout/PatientShell";
import DashboardPage from "@/pages/DashboardPage";
import OnboardPage from "@/pages/OnboardPage";
import PatientsPage from "@/pages/PatientsPage";
import PatientDetailPage from "@/pages/PatientDetailPage";
import DoctorInboxPage from "@/pages/DoctorInboxPage";
import EscalationDetailPage from "@/pages/EscalationDetailPage";
import InsightsPage from "@/pages/InsightsPage";
import PromptsPage from "@/pages/PromptsPage";
import PatientBookingPage from "@/pages/PatientBookingPage";
import NotFoundPage from "@/pages/NotFoundPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "onboard", element: <OnboardPage /> },
      { path: "patients", element: <PatientsPage /> },
      { path: "patients/:patientId", element: <PatientDetailPage /> },
      { path: "doctor", element: <Navigate to="/doctor/inbox" replace /> },
      { path: "doctor/inbox", element: <DoctorInboxPage /> },
      { path: "doctor/escalations/:escId", element: <EscalationDetailPage /> },
      { path: "insights", element: <InsightsPage /> },
      { path: "prompts", element: <PromptsPage /> },
    ],
  },
  {
    path: "/p",
    element: <PatientShell />,
    children: [
      { path: "booking/:proposalId", element: <PatientBookingPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
