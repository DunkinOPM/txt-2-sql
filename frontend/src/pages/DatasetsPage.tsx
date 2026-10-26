import React, { useEffect, useState } from 'react';
import { Database, RefreshCw, AlertCircle, CheckCircle2 } from 'lucide-react';
import { apiClient } from '../api/client';
import { DatasetSummary } from '../types/api';
import { DatasetUpload } from '../components/datasets/DatasetUpload';
import { DatasetCard } from '../components/datasets/DatasetCard';
import { SchemaViewer } from '../components/datasets/SchemaViewer';
import { DatasetPreviewModal } from '../components/datasets/DatasetPreview';
import { DeleteDatasetDialog } from '../components/datasets/DeleteDatasetDialog';

export const DatasetsPage: React.FC = () => {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Modals state
  const [schemaDataset, setSchemaDataset] = useState<DatasetSummary | null>(null);
  const [previewDataset, setPreviewDataset] = useState<DatasetSummary | null>(null);
  const [deletingDataset, setDeletingDataset] = useState<DatasetSummary | null>(null);

  const fetchDatasets = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.listDatasets();
      setDatasets(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load datasets');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDatasets();
  }, []);

  const handleUploadSuccess = (newDataset: DatasetSummary) => {
    setDatasets((prev) => [newDataset, ...prev]);
    setSuccessMessage(`Dataset "${newDataset.display_name}" imported successfully (${newDataset.row_count} rows, ${newDataset.column_count} columns).`);
    setTimeout(() => setSuccessMessage(null), 5000);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingDataset) return;
    await apiClient.deleteDataset(deletingDataset.id);
    setDatasets((prev) => prev.filter((d) => d.id !== deletingDataset.id));
    setSuccessMessage(`Dataset "${deletingDataset.display_name}" deleted.`);
    setDeletingDataset(null);
    setTimeout(() => setSuccessMessage(null), 4000);
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Dataset Management</h1>
          <p className="text-xs text-slate-500 mt-1">
            Upload CSV or XLSX tabular files, inspect inferred schemas, and preview dynamic PostgreSQL tables.
          </p>
        </div>

        <button
          onClick={fetchDatasets}
          disabled={loading}
          aria-label="Refresh datasets list"
          className="inline-flex items-center space-x-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 bg-white border border-slate-200 px-3 py-1.5 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 self-start sm:self-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div role="status" aria-live="polite" className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-lg text-xs flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span className="font-medium">{successMessage}</span>
          </div>
          <button
            onClick={() => setSuccessMessage(null)}
            aria-label="Dismiss notification"
            className="text-emerald-600 hover:text-emerald-900 text-xs font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 rounded px-1"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div role="alert" aria-live="assertive" className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-lg text-xs flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 text-rose-500 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Upload Box */}
      <section>
        <DatasetUpload onUploadSuccess={handleUploadSuccess} />
      </section>

      {/* Datasets Catalog Section */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-900 flex items-center space-x-2">
            <Database className="w-4 h-4 text-brand-600" />
            <span>Imported Datasets</span>
            <span className="text-xs font-normal text-slate-400 font-mono">({datasets.length})</span>
          </h2>
        </div>

        {loading && datasets.length === 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-white border border-slate-200 rounded-xl p-5 space-y-3 animate-pulse">
                <div className="h-4 bg-slate-200 rounded w-1/2"></div>
                <div className="h-3 bg-slate-100 rounded w-3/4"></div>
                <div className="h-12 bg-slate-50 rounded"></div>
              </div>
            ))}
          </div>
        ) : datasets.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-xl p-12 text-center">
            <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-3 text-slate-400">
              <Database className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-semibold text-slate-800">No datasets uploaded yet</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              Upload your first CSV or Excel file above to start exploring your structured data with natural language.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {datasets.map((dataset) => (
              <DatasetCard
                key={dataset.id}
                dataset={dataset}
                onInspectSchema={setSchemaDataset}
                onPreviewData={setPreviewDataset}
                onDelete={setDeletingDataset}
              />
            ))}
          </div>
        )}
      </section>

      {/* Modals */}
      {schemaDataset && (
        <SchemaViewer dataset={schemaDataset} onClose={() => setSchemaDataset(null)} />
      )}

      {previewDataset && (
        <DatasetPreviewModal dataset={previewDataset} onClose={() => setPreviewDataset(null)} />
      )}

      {deletingDataset && (
        <DeleteDatasetDialog
          dataset={deletingDataset}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeletingDataset(null)}
        />
      )}
    </div>
  );
};
