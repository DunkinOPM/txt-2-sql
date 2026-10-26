import React, { useEffect, useState } from 'react';
import { X, Eye, Loader2, AlertCircle } from 'lucide-react';
import { apiClient } from '../../api/client';
import { DatasetSummary, DatasetPreview } from '../../types/api';

interface DatasetPreviewProps {
  dataset: DatasetSummary;
  onClose: () => void;
}

export const DatasetPreviewModal: React.FC<DatasetPreviewProps> = ({ dataset, onClose }) => {
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    apiClient
      .getDatasetPreview(dataset.id, 25)
      .then((data) => {
        setPreview(data);
        setLoading(false);
      })
      .catch((err: any) => {
        setError(err.message || 'Failed to fetch dataset preview');
        setLoading(false);
      });
  }, [dataset.id]);

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-5xl w-full overflow-hidden border border-slate-200 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 bg-brand-50 rounded-lg text-brand-600 border border-brand-100">
              <Eye className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">{dataset.display_name} — Data Preview</h2>
              <p className="text-xs text-slate-500">
                Displaying sample rows from physical PostgreSQL table
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto flex-1">
          {loading ? (
            <div className="py-16 flex flex-col items-center justify-center space-y-2 text-slate-500">
              <Loader2 className="w-8 h-8 animate-spin text-brand-600" />
              <p className="text-xs">Loading sample rows from PostgreSQL...</p>
            </div>
          ) : error ? (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg flex items-center space-x-2 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : preview ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>
                  Showing first <strong className="text-slate-800">{preview.total_preview_rows}</strong> rows of{' '}
                  <strong className="text-slate-800">{preview.total_dataset_rows.toLocaleString()}</strong> total rows
                </span>
                <span className="text-[11px] text-slate-400">
                  Bounded preview (max 25 rows)
                </span>
              </div>

              <div className="border border-slate-200 rounded-lg overflow-x-auto shadow-sm">
                <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
                  <thead className="bg-slate-50 text-slate-700 font-semibold">
                    <tr>
                      <th className="px-4 py-2.5 text-slate-400 font-mono text-[11px] border-r border-slate-200 bg-slate-100/50 w-12 text-center">
                        #
                      </th>
                      {preview.internal_columns.map((colKey, idx) => (
                        <th key={colKey} className="px-4 py-2.5 whitespace-nowrap">
                          <div className="flex flex-col">
                            <span className="font-semibold text-slate-900">{preview.columns[idx]}</span>
                            <span className="text-[10px] text-slate-400 font-mono font-normal">
                              {colKey} ({preview.column_types[colKey]})
                            </span>
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
                    {preview.rows.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-slate-50/80">
                        <td className="px-4 py-2 text-slate-400 text-center border-r border-slate-100 bg-slate-50/30">
                          {rIdx + 1}
                        </td>
                        {preview.internal_columns.map((colKey) => {
                          const val = row[colKey];
                          const isNull = val === null || val === undefined;
                          return (
                            <td key={colKey} className="px-4 py-2 whitespace-nowrap text-slate-700">
                              {isNull ? (
                                <span className="text-slate-300 italic">null</span>
                              ) : typeof val === 'boolean' ? (
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                    val ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
                                  }`}
                                >
                                  {val ? 'true' : 'false'}
                                </span>
                              ) : (
                                String(val)
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-semibold text-slate-700 hover:text-slate-900 bg-white border border-slate-300 rounded-lg hover:bg-slate-100 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

