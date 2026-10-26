import React, { useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { DatasetSummary } from '../../types/api';
import { useFocusTrap } from '../../hooks/useFocusTrap';

interface DeleteDatasetDialogProps {
  dataset: DatasetSummary;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

export const DeleteDatasetDialog: React.FC<DeleteDatasetDialogProps> = ({
  dataset,
  onConfirm,
  onCancel,
}) => {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Focus trapping, initial focus, Escape handling, and focus restoration
  const dialogRef = useFocusTrap<HTMLDivElement>({
    isOpen: true,
    onClose: deleting ? undefined : onCancel,
  });

  const handleConfirm = async () => {
    setDeleting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err: any) {
      setError(err.message || 'Failed to delete dataset');
      setDeleting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-dialog-title"
      ref={dialogRef}
      tabIndex={-1}
      className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 focus-visible:outline-hidden"
    >
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 border border-slate-200">
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-full bg-rose-50 text-rose-600 border border-rose-100 flex items-center justify-center shrink-0" aria-hidden="true">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h3 id="delete-dialog-title" className="text-base font-bold text-slate-900">
              Delete Dataset
            </h3>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Are you sure you want to delete <strong className="text-slate-800">{dataset.display_name}</strong>?
            </p>
            <p className="text-xs text-rose-600 mt-2 bg-rose-50 p-2.5 rounded-lg border border-rose-100">
              This action permanently drops the physical PostgreSQL table in schema <code className="font-mono">uploaded_data</code> and removes all associated column metadata.
            </p>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="mt-3 p-2.5 bg-rose-50 text-rose-700 text-xs rounded-lg border border-rose-200"
          >
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center justify-end space-x-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            className="px-4 py-2 text-xs font-semibold text-slate-700 hover:text-slate-900 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-1"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={deleting}
            className="px-4 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg shadow-2xs transition-colors flex items-center space-x-1.5 disabled:opacity-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-1"
          >
            {deleting && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />}
            <span>{deleting ? 'Deleting...' : 'Delete permanently'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
