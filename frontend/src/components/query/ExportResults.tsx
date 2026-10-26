import React from 'react';
import { Download } from 'lucide-react';
import { apiClient } from '../../api/client';

interface ExportResultsProps {
  queryId: string;
}

export const ExportResults: React.FC<ExportResultsProps> = ({ queryId }) => {
  const exportUrl = apiClient.getExportUrl(queryId);

  return (
    <a
      href={exportUrl}
      download
      className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 hover:text-slate-900 shadow-sm transition-colors"
      title="Download query results as CSV"
      aria-label="Export results to CSV"
    >
      <Download className="w-3.5 h-3.5 text-slate-500" />
      <span>Export CSV</span>
    </a>
  );
};
