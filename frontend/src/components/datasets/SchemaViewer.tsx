import React, { useEffect, useState } from 'react';
import { X, Table, Loader2, AlertCircle, Shield } from 'lucide-react';
import { apiClient } from '../../api/client';
import { DatasetSummary, DatasetSchema } from '../../types/api';

interface SchemaViewerProps {
  dataset: DatasetSummary;
  onClose: () => void;
}

export const SchemaViewer: React.FC<SchemaViewerProps> = ({ dataset, onClose }) => {
  const [schema, setSchema] = useState<DatasetSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    apiClient
      .getDatasetSchema(dataset.id)
      .then((data) => {
        setSchema(data);
        setLoading(false);
      })
      .catch((err: any) => {
        setError(err.message || 'Failed to fetch dataset schema');
        setLoading(false);
      });
  }, [dataset.id]);

  const getTypeBadgeClass = (type: string) => {
    switch (type) {
      case 'BIGINT':
      case 'INTEGER':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      case 'NUMERIC':
        return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'BOOLEAN':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      case 'TIMESTAMPTZ':
        return 'bg-indigo-50 text-indigo-700 border-indigo-200';
      default:
        return 'bg-blue-50 text-blue-700 border-blue-200';
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-3xl w-full overflow-hidden border border-slate-200 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 bg-brand-50 rounded-lg text-brand-600 border border-brand-100">
              <Table className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">{dataset.display_name} — Schema</h2>
              <p className="text-xs text-slate-500 font-mono">
                PostgreSQL table: uploaded_data.{schema?.table_name || '...'}
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
            <div className="py-12 flex flex-col items-center justify-center space-y-2 text-slate-500">
              <Loader2 className="w-8 h-8 animate-spin text-brand-600" />
              <p className="text-xs">Loading schema metadata...</p>
            </div>
          ) : error ? (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg flex items-center space-x-2 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : schema ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs text-slate-500 pb-2">
                <span>
                  Total Columns: <strong className="text-slate-800">{schema.column_count}</strong>
                </span>
                <span>
                  Total Rows: <strong className="text-slate-800">{schema.row_count.toLocaleString()}</strong>
                </span>
              </div>

              <div className="border border-slate-200 rounded-lg overflow-hidden">
                <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
                  <thead className="bg-slate-50 text-slate-600 font-semibold">
                    <tr>
                      <th className="px-4 py-2.5">#</th>
                      <th className="px-4 py-2.5">Original Header</th>
                      <th className="px-4 py-2.5">Normalized Identifier</th>
                      <th className="px-4 py-2.5">Inferred PostgreSQL Type</th>
                      <th className="px-4 py-2.5">Sample Values</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {schema.columns.map((col) => (
                      <tr key={col.id} className="hover:bg-slate-50/60">
                        <td className="px-4 py-2.5 text-slate-400 font-mono text-[11px]">
                          {col.ordinal_position}
                        </td>
                        <td className="px-4 py-2.5 font-medium text-slate-900">
                          {col.original_name}
                        </td>
                        <td className="px-4 py-2.5 font-mono text-slate-600 text-[11px]">
                          {col.internal_name}
                        </td>
                        <td className="px-4 py-2.5">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${getTypeBadgeClass(
                              col.inferred_type
                            )}`}
                          >
                            {col.inferred_type}
                          </span>
                        </td>
                        <td className="px-4 py-2.5">
                          {col.sample_values && col.sample_values.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {col.sample_values.map((val, idx) => (
                                <span
                                  key={idx}
                                  className="bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded text-[10px] font-mono border border-slate-200"
                                >
                                  {String(val)}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-slate-400 italic text-[11px]">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-[11px] text-slate-500 flex items-start space-x-2">
                <Shield className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                <span>
                  <strong>Privacy Rule Applied:</strong> Only low-cardinality non-sensitive categorical columns store minimal sample values for query formulation. Sensitive columns, numbers, and dates are scrubbed.
                </span>
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

