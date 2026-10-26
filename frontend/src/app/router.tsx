import { createBrowserRouter } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import { WorkspacePage } from '../pages/WorkspacePage';
import { DatasetsPage } from '../pages/DatasetsPage';
import { QueryHistoryPage } from '../pages/QueryHistoryPage';
import { LoginPage } from '../pages/LoginPage';
import { ProtectedRoute } from '../components/common/ProtectedRoute';

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      {
        index: true,
        element: <WorkspacePage />,
      },
      {
        path: 'datasets',
        element: <DatasetsPage />,
      },
      {
        path: 'history',
        element: <QueryHistoryPage />,
      },
    ],
  },
]);
