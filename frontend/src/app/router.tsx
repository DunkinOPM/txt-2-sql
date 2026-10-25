import { createBrowserRouter } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import { WorkspacePage } from '../pages/WorkspacePage';
import { DatasetsPage } from '../pages/DatasetsPage';
import { QueryHistoryPage } from '../pages/QueryHistoryPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
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

