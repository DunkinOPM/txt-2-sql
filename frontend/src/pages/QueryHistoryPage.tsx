import React, { useEffect, useState, useCallback } from 'react';
import {
  History,
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
  Database,
  Calendar,
  Clock,
  ArrowRight,
  AlertCircle,
  Eye,
  RotateCcw,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { QueryHistoryItem, DatasetSummary } from '../types/api';
import { apiClient } from '../api/client';
import { QueryStatus } from '../components/query/QueryStatus';
import { HistoryDetailModal } from '../components/query/HistoryDetailModal';

const PAGE_SIZE = 15;

export const QueryHistoryPage: React.FC = () => {
  const navigate = useNavigate();

  const [queries, setQueries] = useState<QueryHistoryItem[]>([]);
  const [totalQueries, setTotalQueries] = useState<number>(0);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [page, setPage] = useState<number>(1);

  // Modal inspection
  const [inspectingQueryId, setInspectingQueryId] = useState<string | null>(null);

  // Load datasets for dropdown filter
  useEffect(() => {
    apiClient
      .listDatasets()
      .then((data: DatasetSummary[]) => setDatasets(data))
      .catch(() => {});
  }, []);

  const loadQueries = useCallback(() => {
    setLoading(true);
    setError(null);
    const offset = (page - 1) * PAGE_SIZE;

    apiClient
      .getQueries({
        datasetId: selectedDatasetId || undefined,
        status: selectedStatus || undefined,
        search: searchQuery.trim() || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .then((res) => {
        setQueries(res.items);
        setTotalQueries(res.total);
      })
      .catch((err: any) => {
        setError(err.message || 'Failed to load query history');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selectedDatasetId, selectedStatus, searchQuery, page]);

  useEffect(() => {
    loadQueries();
  }, [loadQueries]);

  // Reset to page 1 on filter change
  const handleDatasetChange = (id: string) => {
    setSelectedDatasetId(id);
    setPage(1);
  };

  const handleStatusChange = (status: string) => {
    setSelectedStatus(status);
    setPage(1);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadQueries();
  };

  const totalPages = Math.ceil(totalQueries / PAGE_SIZE) || 1;

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 flex items-center space-x-2.5">
            <History className="w-5 h-5 text-brand-600" />
            <span>Query History</span>
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Audit past natural language queries, multi-turn clarifications, generated SQL, and performance metrics.
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
            Total Queries: {totalQueries}
          </span>
        </div>
      </div>

      {/* Filter and Search Controls */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Search bar */}
          <form onSubmit={handleSearchSubmit} className="relative md:col-span-2">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input aria-label="Search past queries"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search past questions..."
              className="w-full pl-9 pr-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-800 placeholder-slate-400 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
            />
          </form>

          {/* Dataset Selector */}
          <div className="relative">
            <select aria-label="Filter by dataset"
              value={selectedDatasetId}
              onChange={(e) => handleDatasetChange(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            >
              <option value="">All Datasets</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.display_name} ({d.row_count} rows)
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Status Filter Pills */}
        <div className="flex items-center space-x-2 overflow-x-auto pt-1 pb-0.5">
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center shrink-0">
            <Filter className="w-3 h-3 mr-1" /> Status:
          </span>
          {[
            { label: 'All', value: '' },
            { label: 'Completed', value: 'completed' },
            { label: 'Awaiting Clarification', value: 'awaiting_clarification' },
            { label: 'Ready for SQL', value: 'ready_for_sql' },
            { label: 'Rejected', value: 'rejected' },
            { label: 'Failed', value: 'failed' },
          ].map((pill) => (
            <button
              key={pill.value}
              type="button"
              onClick={() => handleStatusChange(pill.value)}
              className={`text-xs px-2.5 py-1 rounded-lg font-medium whitespace-nowrap transition-colors ${
                selectedStatus === pill.value
                  ? 'bg-brand-600 text-white shadow-2xs focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500'
              }`}
            >
              {pill.label}
            </button>
          ))}
          {(selectedDatasetId || selectedStatus || searchQuery) && (
            <button
              type="button"
              onClick={() => {
                setSelectedDatasetId('');
                setSelectedStatus('');
                setSearchQuery('');
                setPage(1);
              }}
              className="text-[11px] text-rose-600 hover:text-rose-800 font-semibold px-2 py-1 ml-auto shrink-0 flex items-center space-x-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 rounded"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Reset Filters</span>
            </button>
          )}
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div role="alert" aria-live="assertive" className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-xl text-xs flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 text-rose-500 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* History Items Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
        {loading ? (
          <div className="p-12 text-center space-y-3">
            <div className="w-8 h-8 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-xs text-slate-500 font-medium">Loading query history...</p>
          </div>
        ) : queries.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center mx-auto text-slate-400">
              <History className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-semibold text-slate-800">No Queries Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              {selectedDatasetId || selectedStatus || searchQuery
                ? 'No past queries match your active filter criteria. Try adjusting your search or filters.'
                : 'No queries have been submitted yet. Go to the Workspace to query your uploaded datasets.'}
            </p>
          </div>
        ) : (
          <div tabIndex={0} role="region" aria-label="Query history records table" className="overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
            <table className="w-full text-left text-xs text-slate-600 border-collapse">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Question</th>
                  <th className="py-3 px-4">Dataset</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Rows</th>
                  <th className="py-3 px-4">Duration</th>
                  <th className="py-3 px-4">Date</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-normal">
                {queries.map((q) => (
                  <tr
                    key={q.id}
                    className="hover:bg-slate-50/70 transition-colors cursor-pointer"
                    onClick={() => setInspectingQueryId(q.id)}
                  >
                    <td className="py-3.5 px-4 max-w-xs sm:max-w-md">
                      <div className="font-medium text-slate-900 truncate">
                        {q.original_question}
                      </div>
                      {q.refined_question && (
                        <div className="text-[11px] text-amber-700 truncate mt-0.5">
                          ↳ {q.refined_question}
                        </div>
                      )}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <span className="inline-flex items-center text-slate-700 font-medium">
                        <Database className="w-3 h-3 mr-1 text-slate-400" />
                        {q.dataset_name}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <QueryStatus status={q.status} category={q.category} />
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap font-mono text-slate-700">
                      {q.result_row_count !== null && q.result_row_count !== undefined ? q.result_row_count.toLocaleString() : '—'}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap text-slate-500">
                      {q.execution_duration_ms !== null ? (
                        <span className="inline-flex items-center">
                          <Clock className="w-3 h-3 mr-1 text-slate-400" />
                          {q.execution_duration_ms}ms
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap text-slate-500">
                      <span className="inline-flex items-center">
                        <Calendar className="w-3 h-3 mr-1 text-slate-400" />
                        {new Date(q.created_at).toLocaleDateString()}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap text-right space-x-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setInspectingQueryId(q.id);
                        }}
                        className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                      >
                        <Eye className="w-3 h-3" />
                        <span>Inspect</span>
                      </button>

                      {q.status === 'awaiting_clarification' && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/?query_id=${q.id}`);
                          }}
                          className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold shadow-2xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                        >
                          <span>Resume</span>
                          <ArrowRight className="w-3 h-3" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Footer */}
        {totalQueries > 0 && (
          <div className="px-4 py-3 border-t border-slate-200 bg-slate-50/50 flex items-center justify-between text-xs text-slate-600">
            <span>
              Showing <strong>{(page - 1) * PAGE_SIZE + 1}</strong> to{' '}
              <strong>{Math.min(page * PAGE_SIZE, totalQueries)}</strong> of{' '}
              <strong>{totalQueries}</strong> queries
            </span>
            <div className="flex items-center space-x-1.5">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-1 rounded-md border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                aria-label="Previous page"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="px-2 font-medium">
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="p-1 rounded-md border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                aria-label="Next page"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* History Inspection Modal */}
      {inspectingQueryId && (
        <HistoryDetailModal
          queryId={inspectingQueryId}
          onClose={() => setInspectingQueryId(null)}
        />
      )}
    </div>
  );
};
