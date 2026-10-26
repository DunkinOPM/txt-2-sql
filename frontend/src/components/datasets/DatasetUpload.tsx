import React, { useState, useRef } from 'react';
import { UploadCloud, AlertCircle, FileText, Loader2 } from 'lucide-react';
import { apiClient } from '../../api/client';
import { DatasetSummary } from '../../types/api';

interface DatasetUploadProps {
  onUploadSuccess: (dataset: DatasetSummary) => void;
}

export const DatasetUpload: React.FC<DatasetUploadProps> = ({ onUploadSuccess }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setErrorMessage(null);

    // Client-side validations
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (!['.csv', '.xlsx'].includes(ext)) {
      setErrorMessage("Only CSV and XLSX files are supported.");
      return;
    }

    if (file.size > 20 * 1024 * 1024) {
      setErrorMessage("File exceeds 20 MB size limit.");
      return;
    }

    if (file.size === 0) {
      setErrorMessage("File is empty (0 bytes).");
      return;
    }

    setUploading(true);
    try {
      const dataset = await apiClient.uploadDataset(file);
      onUploadSuccess(dataset);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to upload and import dataset.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const onDragLeave = () => {
    setIsDragging(false);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const onFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => !uploading && fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
          isDragging
            ? 'border-brand-500 bg-brand-50/50'
            : 'border-slate-300 hover:border-brand-400 bg-white hover:bg-slate-50/50'
        } ${uploading ? 'opacity-70 cursor-not-allowed pointer-events-none' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx"
          onChange={onFileSelect}
          className="hidden"
          disabled={uploading}
        />

        <div className="flex flex-col items-center justify-center space-y-3">
          {uploading ? (
            <div className="flex flex-col items-center space-y-2">
              <Loader2 className="w-10 h-10 text-brand-600 animate-spin" />
              <p className="text-sm font-semibold text-slate-800">
                Importing dataset & inferring schema...
              </p>
              <p className="text-xs text-slate-500">
                Validating columns, normalizing identifiers, and creating dynamic PostgreSQL table.
              </p>
            </div>
          ) : (
            <>
              <div className="w-12 h-12 bg-brand-50 text-brand-600 rounded-full flex items-center justify-center">
                <UploadCloud className="w-6 h-6" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  Click to upload or drag and drop dataset
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  Supported formats: CSV, XLSX (Max 20 MB, up to 100,000 rows & 250 columns)
                </p>
              </div>
              <div className="flex items-center space-x-2 text-xs text-slate-400">
                <FileText className="w-3.5 h-3.5" />
                <span>Headers normalized deterministically • Types conservatively inferred</span>
              </div>
            </>
          )}
        </div>
      </div>

      {errorMessage && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-lg text-xs flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-500" />
          <span className="font-medium">{errorMessage}</span>
        </div>
      )}
    </div>
  );
};

