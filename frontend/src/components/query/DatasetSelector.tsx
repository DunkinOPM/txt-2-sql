import React from 'react';
import { Database, ChevronDown } from 'lucide-react';
import { DatasetSummary } from '../../types/api';

interface DatasetSelectorProps {
  datasets: DatasetSummary[];
  selectedDatasetId: string | null;
  onSelectDataset: (datasetId: string) => void;
  disabled?: boolean;
}

export const DatasetSelector: React.FC<DatasetSelectorProps> = ({
  datasets,
  selectedDatasetId,
  onSelectDataset,
  disabled = false,
}) => {
  const readyDatasets = datasets.filter((d) => d.status === 'ready');
  const selectedDataset = readyDatasets.find((d) => d.id === selectedDatasetId);

  return (
    <div className="flex items-center space-x-3 bg-white border border-slate-200 rounded-xl p-3 shadow-sm">
      <div className="w-9 h-9 rounded-lg bg-brand-50 border border-brand-100 flex items-center justify-center text-brand-600 shrink-0">
        <Database className="w-4 h-4" />
      </div>

      <div className="flex-1 min-w-0">
        <label htmlFor="dataset-select" className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-0.5">
          Active Dataset
        </label>
        <div className="relative">
          <select
            id="dataset-select"
            value={selectedDatasetId || ''}
            onChange={(e) => onSelectDataset(e.target.value)}
            disabled={disabled || readyDatasets.length === 0}
            className="w-full text-xs font-semibold text-slate-900 bg-transparent pr-8 border-none focus:outline-none focus:ring-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed appearance-none"
          >
            {readyDatasets.length === 0 ? (
              <option value="" disabled>
                No datasets imported yet — upload in Datasets tab
              </option>
            ) : (
              readyDatasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.display_name} ({d.row_count.toLocaleString()} rows • {d.column_count} cols)
                </option>
              ))
            )}
          </select>
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-1 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </div>

      {selectedDataset && (
        <span className="hidden sm:inline-flex text-[10px] font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          {selectedDataset.file_format.toUpperCase()}
        </span>
      )}
    </div>
  );
};
