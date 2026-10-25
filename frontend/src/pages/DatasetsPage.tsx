import React from 'react';
import { Database, UploadCloud } from 'lucide-react';

export const DatasetsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Dataset Management</h2>
          <p className="text-sm text-slate-500">
            Upload CSV or XLSX tabular data and inspect schema structure.
          </p>
        </div>
      </div>

      <div className="border-2 border-dashed border-slate-300 rounded-xl p-12 text-center bg-white hover:border-brand-400 transition-colors cursor-pointer">
        <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-3 text-slate-500">
          <UploadCloud className="w-6 h-6" />
        </div>
        <h3 className="text-sm font-semibold text-slate-800 mb-1">
          Upload CSV or XLSX file
        </h3>
        <p className="text-xs text-slate-500 max-w-sm mx-auto mb-4">
          Drag and drop your dataset here, or browse files. Supported limits: max 20 MB, 100,000 rows, 250 columns.
        </p>
        <span className="inline-flex items-center text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-100 text-slate-700 border border-slate-200">
          <Database className="w-3.5 h-3.5 mr-1.5 text-brand-600" />
          Scheduled for Phase 02
        </span>
      </div>
    </div>
  );
};

