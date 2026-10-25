import React, { useEffect, useState } from 'react';
import { MessageSquare, Sparkles, AlertCircle, Database, CheckCircle2 } from 'lucide-react';
import { apiClient } from '../api/client';
import { HealthResponse } from '../types/api';

export const WorkspacePage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .getHealth()
      .then((data) => {
        setHealth(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Unable to connect to backend server');
        setLoading(false);
      });
  }, []);

  return (
    <div className="space-y-6">
      {/* System Status Banner */}
      {loading ? (
        <div className="bg-slate-100 border border-slate-200 text-slate-600 px-4 py-3 rounded-lg text-sm flex items-center">
          <span className="w-2 h-2 rounded-full bg-slate-400 animate-pulse mr-2.5"></span>
          Verifying backend connectivity...
        </div>
      ) : error ? (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-lg text-sm flex items-center">
          <AlertCircle className="w-4 h-4 mr-2 text-rose-500 shrink-0" />
          <span>Backend Connection Warning: {error}</span>
        </div>
      ) : (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-lg text-sm flex items-center justify-between">
          <div className="flex items-center">
            <CheckCircle2 className="w-4 h-4 mr-2 text-emerald-600 shrink-0" />
            <span>
              Connected to backend v{health?.version} (Database: {health?.database}, Read-Only Role: {health?.readonly_database})
            </span>
          </div>
          <span className="text-xs font-mono bg-emerald-100 text-emerald-900 px-2 py-0.5 rounded">
            Phase 01 Active
          </span>
        </div>
      )}

      {/* Main Workspace Hero Card */}
      <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center max-w-2xl mx-auto my-12">
        <div className="w-14 h-14 bg-brand-50 border border-brand-100 rounded-full flex items-center justify-center mx-auto mb-4 text-brand-600">
          <MessageSquare className="w-7 h-7" />
        </div>
        <h2 className="text-xl font-bold text-slate-900 mb-2">
          Clarification-Driven Conversational Text-to-SQL
        </h2>
        <p className="text-sm text-slate-600 mb-6 leading-relaxed">
          Ask questions in natural language against your tabular datasets. When queries are ambiguous or data is missing, the assistant asks for clarification rather than making unwarranted assumptions.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-left max-w-lg mx-auto">
          <div className="border border-slate-200 rounded-lg p-4 bg-slate-50/50">
            <div className="flex items-center space-x-2 text-slate-900 font-semibold text-xs mb-1">
              <Database className="w-4 h-4 text-brand-600" />
              <span>Step 1: Upload Dataset</span>
            </div>
            <p className="text-xs text-slate-500">
              Go to Datasets to upload CSV/XLSX files, inspect column types, and preview rows.
            </p>
          </div>

          <div className="border border-slate-200 rounded-lg p-4 bg-slate-50/50">
            <div className="flex items-center space-x-2 text-slate-900 font-semibold text-xs mb-1">
              <Sparkles className="w-4 h-4 text-brand-600" />
              <span>Step 2: Ask & Clarify</span>
            </div>
            <p className="text-xs text-slate-500">
              Query your data naturally, clarify intent if needed, and receive verified SQL & tabular results.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

