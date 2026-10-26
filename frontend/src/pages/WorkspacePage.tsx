import React, { useEffect, useState, useRef } from 'react';
import { Sparkles, AlertCircle, Database, ArrowRight, Play, Loader2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { DatasetSummary, QueryResponse } from '../types/api';
import { DatasetSelector } from '../components/query/DatasetSelector';
import { ChatMessage } from '../components/query/ChatMessage';
import { ClarificationCard } from '../components/query/ClarificationCard';
import { QueryInput } from '../components/query/QueryInput';
import { QueryStatus } from '../components/query/QueryStatus';
import { SQLViewer } from '../components/query/SQLViewer';
import { ResultsTable } from '../components/query/ResultsTable';
import { ExportResults } from '../components/query/ExportResults';

export const WorkspacePage: React.FC = () => {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [currentQuery, setCurrentQuery] = useState<QueryResponse | null>(null);
  const [loadingDatasets, setLoadingDatasets] = useState(true);
  const [executingQuery, setExecutingQuery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load available datasets
  useEffect(() => {
    setLoadingDatasets(true);
    apiClient
      .listDatasets()
      .then((data) => {
        setDatasets(data);
        const readyOnes = data.filter((d) => d.status === 'ready');
        if (readyOnes.length > 0) {
          setSelectedDatasetId(readyOnes[0].id);
        }
        setLoadingDatasets(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load datasets');
        setLoadingDatasets(false);
      });
  }, []);

  // Auto-scroll chat to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentQuery]);

  const handleSendMessage = async (question: string) => {
    if (!selectedDatasetId) {
      setError('Please select or upload a dataset before submitting a query.');
      return;
    }
    setError(null);
    try {
      const response = await apiClient.createQuery(selectedDatasetId, question);
      setCurrentQuery(response);
    } catch (err: any) {
      setError(err.message || 'Failed to submit query');
    }
  };

  const handleClarificationAnswer = async (selectedOption?: string, freeTextAnswer?: string) => {
    if (!currentQuery) return;
    setError(null);
    try {
      const updated = await apiClient.submitClarification(currentQuery.id, selectedOption, freeTextAnswer);
      setCurrentQuery(updated);
    } catch (err: any) {
      setError(err.message || 'Failed to submit clarification');
    }
  };

  const handleExecuteQuery = async () => {
    if (!currentQuery) return;
    setExecutingQuery(true);
    setError(null);
    try {
      const executed = await apiClient.executeQuery(currentQuery.id);
      setCurrentQuery(executed);
    } catch (err: any) {
      setError(err.message || 'Failed to execute query');
    } finally {
      setExecutingQuery(false);
    }
  };

  const activeDataset = datasets.find((d) => d.id === selectedDatasetId);
  const isAwaiting = currentQuery?.status === 'awaiting_clarification';
  const isProcessing = Boolean(executingQuery || (currentQuery && ['generating_sql', 'validating_sql', 'executing'].includes(currentQuery.status)));

  return (
    <div className="flex flex-col h-[calc(100vh-7.5rem)] space-y-4">
      {/* Top Controls: Dataset Selector and Active Query Status */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <div className="max-w-md w-full">
          <DatasetSelector
            datasets={datasets}
            selectedDatasetId={selectedDatasetId}
            onSelectDataset={(id) => {
              setSelectedDatasetId(id);
              setCurrentQuery(null);
              setError(null);
            }}
            disabled={loadingDatasets}
          />
        </div>

        {currentQuery && (
          <div className="bg-white border border-slate-200 rounded-xl px-4 py-2.5 shadow-sm flex items-center justify-between sm:justify-end space-x-3">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Query State:
            </span>
            <QueryStatus status={currentQuery.status} category={currentQuery.category} />
          </div>
        )}
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-2.5 rounded-lg text-xs flex items-center space-x-2 shrink-0">
          <AlertCircle className="w-4 h-4 text-rose-500 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 bg-slate-50/60 border border-slate-200 rounded-2xl p-4 sm:p-6 overflow-y-auto space-y-4 shadow-inner">
        {datasets.filter((d) => d.status === 'ready').length === 0 ? (
          /* Empty State: No Datasets Uploaded */
          <div className="h-full flex flex-col items-center justify-center text-center max-w-sm mx-auto space-y-3 py-12">
            <div className="w-12 h-12 rounded-full bg-brand-50 border border-brand-100 text-brand-600 flex items-center justify-center">
              <Database className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-bold text-slate-800">No Datasets Ready</h3>
            <p className="text-xs text-slate-500">
              Upload your first CSV or XLSX file to begin querying your tabular data with conversational clarification.
            </p>
            <Link
              to="/datasets"
              className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-lg bg-brand-600 text-white text-xs font-semibold hover:bg-brand-700 shadow-sm transition-colors"
            >
              <span>Go to Datasets</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        ) : !currentQuery ? (
          /* Empty State: Ready Dataset, No Query Yet */
          <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto space-y-4 py-12">
            <div className="w-12 h-12 rounded-full bg-brand-50 border border-brand-100 text-brand-600 flex items-center justify-center">
              <Sparkles className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-800">
                Ready to Query <span className="text-brand-600 font-semibold">{activeDataset?.display_name}</span>
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                Type a natural language question below. Clear questions are directly translated into read-only SQL, validated, and executed.
              </p>
            </div>

            <div className="bg-white border border-slate-200 rounded-xl p-3 text-left w-full space-y-1.5 text-xs">
              <span className="font-semibold text-slate-700 block text-[11px] uppercase tracking-wider">
                Ambiguity-Aware Examples:
              </span>
              <ul className="text-slate-500 space-y-1 list-disc list-inside text-[11px]">
                <li>Clear questions will be executed against authorized read-only data.</li>
                <li>Ambiguous terms (e.g. &ldquo;top&rdquo; or &ldquo;recent&rdquo;) will trigger follow-up options.</li>
                <li>Missing columns will be identified without inventing answers.</li>
              </ul>
            </div>
          </div>
        ) : (
          /* Conversational Thread */
          <div className="space-y-4">
            {currentQuery.turns.map((turn) => (
              <ChatMessage
                key={turn.id}
                turn={turn}
                refinedQuestion={currentQuery.refined_question}
              />
            ))}

            {/* Interactive Clarification Card if Awaiting Response */}
            {currentQuery.status === 'awaiting_clarification' && currentQuery.clarification_question && (
              <ClarificationCard
                question={currentQuery.clarification_question}
                options={currentQuery.clarification_options}
                onSubmitAnswer={handleClarificationAnswer}
              />
            )}

            {/* Ready for SQL State with explicit trigger */}
            {currentQuery.status === 'ready_for_sql' && (
              <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl p-4 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-sm">
                <div className="flex items-center space-x-2.5">
                  <Sparkles className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>
                    <strong>Query Clear & Verified:</strong> Ready for AST validation and read-only execution.
                  </span>
                </div>
                <button
                  onClick={handleExecuteQuery}
                  disabled={executingQuery}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition-colors shrink-0 disabled:opacity-50"
                >
                  {executingQuery ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Executing...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5" />
                      <span>Execute Query</span>
                    </>
                  )}
                </button>
              </div>
            )}

            {/* In-Flight Pipeline Status Banner */}
            {isProcessing && (
              <div className="bg-purple-50 border border-purple-200 text-purple-800 rounded-xl p-3.5 text-xs flex items-center space-x-2.5">
                <Loader2 className="w-4 h-4 animate-spin text-purple-600 shrink-0" />
                <span>
                  <strong>Processing Query:</strong> Generating SQL, checking AST policy, and executing in read-only transaction...
                </span>
              </div>
            )}

            {/* Completed Results Display */}
            {currentQuery.status === 'completed' && (
              <div className="space-y-3 pt-2">
                {currentQuery.generated_sql && (
                  <SQLViewer sql={currentQuery.generated_sql} />
                )}

                {currentQuery.columns && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-end">
                      <ExportResults queryId={currentQuery.id} />
                    </div>
                    <ResultsTable
                      columns={currentQuery.columns}
                      rows={currentQuery.rows || []}
                      rowCount={currentQuery.result_row_count}
                      durationMs={currentQuery.execution_duration_ms}
                    />
                  </div>
                )}
              </div>
            )}

            {/* Failed Query Banner */}
            {currentQuery.status === 'failed' && (
              <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-xl p-3.5 text-xs flex items-start space-x-2.5">
                <AlertCircle className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <div className="font-semibold text-rose-900">
                    Execution Error [{currentQuery.error_code || 'QUERY_FAILED'}]
                  </div>
                  <div className="text-rose-700">
                    {currentQuery.assistant_message || currentQuery.error_message || 'The query could not be executed.'}
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Bottom Query Input Bar */}
      <div className="shrink-0">
        <QueryInput
          onSendMessage={handleSendMessage}
          disabled={!selectedDatasetId || isAwaiting || isProcessing}
          placeholder={
            isAwaiting
              ? 'Please answer the clarification above to continue...'
              : isProcessing
              ? 'Query execution in progress...'
              : activeDataset
              ? `Ask a question about ${activeDataset.display_name}...`
              : 'Select a dataset to begin querying...'
          }
        />
      </div>
    </div>
  );
};
