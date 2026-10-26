import React from 'react';
import { FileSpreadsheet, FileText, Table, Eye, Trash2, Calendar } from 'lucide-react';
import { DatasetSummary } from '../../types/api';

interface DatasetCardProps {
  dataset: DatasetSummary;
  onInspectSchema: (dataset: DatasetSummary) => void;
  onPreviewData: (dataset: DatasetSummary) => void;
  onDelete: (dataset: DatasetSummary) => void;
}

export const DatasetCard: React.FC<DatasetCardProps> = ({
  dataset,
  onInspectSchema,
  onPreviewData,
  onDelete,
}) => {
  const formattedDate = new Date(dataset.created_at).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow flex flex-col justify-between">
      <div>
        {/* Header: Title and format badge */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-lg bg-brand-50 border border-brand-100 flex items-center justify-center text-brand-600 shrink-0">
              {dataset.file_format === 'xlsx' ? (
                <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
              ) : (
                <FileText className="w-5 h-5 text-brand-600" />
              )}
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900 leading-snug line-clamp-1" title={dataset.display_name}>
                {dataset.display_name}
              </h3>
              <p className="text-xs text-slate-500 font-mono line-clamp-1" title={dataset.original_filename}>
                {dataset.original_filename}
              </p>
            </div>
          </div>

          <span
            className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
              dataset.file_format === 'xlsx'
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                : 'bg-blue-50 text-blue-700 border border-blue-200'
            }`}
          >
            {dataset.file_format}
          </span>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-2 gap-2 my-4 bg-slate-50 p-2.5 rounded-lg border border-slate-100 text-xs">
          <div>
            <span className="text-slate-500 block text-[11px]">Rows</span>
            <span className="font-semibold text-slate-800">{dataset.row_count.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-slate-500 block text-[11px]">Columns</span>
            <span className="font-semibold text-slate-800">{dataset.column_count}</span>
          </div>
        </div>

        <div className="flex items-center text-slate-400 text-[11px] mb-4">
          <Calendar className="w-3.5 h-3.5 mr-1" />
          <span>Uploaded {formattedDate}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-3 border-t border-slate-100 space-x-2">
        <div className="flex items-center space-x-1.5">
          <button
            onClick={() => onInspectSchema(dataset)}
            className="flex items-center space-x-1 text-xs font-medium text-slate-700 hover:text-brand-600 bg-white hover:bg-slate-100 px-2.5 py-1.5 rounded-md border border-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            <Table className="w-3.5 h-3.5" />
            <span>Schema</span>
          </button>
          <button
            onClick={() => onPreviewData(dataset)}
            className="flex items-center space-x-1 text-xs font-medium text-slate-700 hover:text-brand-600 bg-white hover:bg-slate-100 px-2.5 py-1.5 rounded-md border border-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            <Eye className="w-3.5 h-3.5" />
            <span>Preview</span>
          </button>
        </div>

        <button
          onClick={() => onDelete(dataset)}
          title="Delete dataset"
          aria-label={`Delete ${dataset.display_name}`}
          className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
