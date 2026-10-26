import React, { useEffect, useState } from 'react';
import {
  X,
  Clock,
  Sparkles,
  AlertCircle,
  ExternalLink,
  Loader2,
  Calendar,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { QueryResponse } from '../../types/api';
import { apiClient } from '../../api/client';
import { QueryStatus } from './QueryStatus';
import { ChatMessage } from './ChatMessage';
import { SQLViewer } from './SQLViewer';
import { ResultsTable } from './ResultsTable';
import { ExportResults } from './ExportResults';

interface HistoryDetailModalProps {
  queryId: string | null;
  onClose: () => void;
}

export const HistoryDetailModal: React.FC<HistoryDetailModalProps> = ({ queryId, onClose }) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!queryId) {
      setQuery(null);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    apiClient
      .getQuery(queryId)
      .then((data) => {
        if (isMounted) setQuery(data);
      })
      .catch((err: any) => {
        if (isMounted) setError(err.message || 'Failed to load query details');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [queryId]);

  if (!queryId) return null;

  const handleOpenInWorkspace = () => {
    onClose();
    navigate(`/?query_id=${queryId}`);
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50/50 shrink-0">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">Query Details</h3>
              <p className="text-[11px] text-slate-500 font-mono">ID: {queryId}</p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            {query && (
              <button
                onClick={handleOpenInWorkspace}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-colors"
                title="Open in conversational workspace"
              >
                <span>{query.status === 'awaiting_clarification' ? 'Resume in Workspace' : 'Open in Workspace'}</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1">
          {loading && (
            <div className="py-16 text-center space-y-3">
              <Loader2 className="w-8 h-8 text-brand-600 animate-spin mx-auto" />
              <p className="text-xs text-slate-500 font-medium">Loading query details...</p>
            </div>
          )}

          {error && (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-xl text-xs flex items-center space-x-3">
              <AlertCircle className="w-5 h-5 text-rose-500 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {query && !loading && (
            <>
              {/* Status and Metadata Card */}
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
                <div>
                  <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                    Status
                  </span>
                  <QueryStatus status={query.status} category={query.category} />
                </div>
                <div>
                  <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                    Created At
                  </span>
                  <span className="inline-flex items-center text-slate-700 font-medium">
                    <Calendar className="w-3.5 h-3.5 mr-1 text-slate-400" />
                    {new Date(query.created_at).toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                    Duration
                  </span>
                  <span className="inline-flex items-center text-slate-700 font-medium">
                    <Clock className="w-3.5 h-3.5 mr-1 text-slate-400" />
                    {query.execution_duration_ms !== null ? `${query.execution_duration_ms}ms` : '—'}
                  </span>
                </div>
                <div>
                  <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                    Rows Returned
                  </span>
                  <span className="text-slate-700 font-medium font-mono">
                    {query.result_row_count !== null && query.result_row_count !== undefined ? query.result_row_count.toLocaleString() : '—'}
                  </span>
                </div>
              </div>

              {/* Original Question Card */}
              <div className="space-y-1.5">
                <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Original Question
                </span>
                <div className="bg-white border border-slate-200 rounded-xl p-3.5 text-xs text-slate-800 font-medium">
                  "{query.original_question}"
                </div>
              </div>

              {query.refined_question && (
                <div className="space-y-1.5">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                    Refined Question (Post-Clarification)
                  </span>
                  <div className="bg-amber-50/50 border border-amber-200 rounded-xl p-3.5 text-xs text-amber-900 font-medium">
                    "{query.refined_question}"
                  </div>
                </div>
              )}

              {/* Conversational Turns */}
              {query.turns && query.turns.length > 0 && (
                <div className="space-y-2.5">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                    Conversation History ({query.turns.length} turns)
                  </span>
                  <div className="space-y-3 bg-slate-50/50 border border-slate-200 rounded-xl p-4">
                    {query.turns.map((turn) => (
                      <ChatMessage
                        key={turn.id}
                        turn={turn}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Generated SQL */}
              {query.generated_sql && (
                <div className="space-y-2">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                    Generated PostgreSQL Query
                  </span>
                  <SQLViewer sql={query.generated_sql} />
                </div>
              )}

              {/* Results Table & Export */}
              {query.columns && query.rows && (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                      Execution Results ({query.result_row_count !== null && query.result_row_count !== undefined ? query.result_row_count : query.rows.length} rows)
                    </span>
                    <ExportResults queryId={query.id} />
                  </div>
                  <ResultsTable
                    columns={query.columns}
                    rows={query.rows}
                    rowCount={query.result_row_count ?? query.rows.length}
                    durationMs={query.execution_duration_ms}
                  />
                </div>
              )}

              {/* Error Code Notice if Failed or Rejected */}
              {(query.status === 'failed' || query.status === 'rejected') && (
                <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 text-xs text-rose-800 space-y-1">
                  <div className="font-bold flex items-center space-x-1.5">
                    <AlertCircle className="w-4 h-4 text-rose-600" />
                    <span>
                      {query.status === 'rejected' ? 'Request Rejected: ' : 'Error Code: '}
                      {query.error_code || (query.status === 'rejected' ? 'REJECTED' : 'QUERY_FAILED')}
                    </span>
                  </div>
                  <p className="text-rose-700">{query.error_message || query.assistant_message}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
