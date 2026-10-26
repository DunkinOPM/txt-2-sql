import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, Table as TableIcon, Clock } from 'lucide-react';

interface ResultsTableProps {
  columns: string[];
  rows: Record<string, any>[];
  rowCount?: number | null;
  durationMs?: number | null;
}

export const ResultsTable: React.FC<ResultsTableProps> = ({
  columns,
  rows,
  rowCount,
  durationMs,
}) => {
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 25;
  const totalRows = rows.length;
  const totalPages = Math.ceil(totalRows / pageSize) || 1;

  const startIndex = (currentPage - 1) * pageSize;
  const currentRows = rows.slice(startIndex, startIndex + pageSize);

  if (!columns || columns.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-4 text-center text-xs text-slate-500">
        No tabular columns returned by this query.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm my-3">
      {/* Header Summary Bar */}
      <div className="bg-slate-50/80 px-4 py-2.5 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
        <div className="flex items-center space-x-2">
          <TableIcon className="w-4 h-4 text-brand-600" />
          <span className="font-semibold text-slate-800">
            Query Results
          </span>
          <span className="text-slate-400">•</span>
          <span>
            {rowCount !== undefined && rowCount !== null ? rowCount : totalRows}{' '}
            {totalRows === 1 ? 'record' : 'records'}
            {totalRows >= 1000 && ' (capped at 1,000 max)'}
          </span>
        </div>

        {durationMs !== undefined && durationMs !== null && (
          <div className="inline-flex items-center space-x-1.5 text-[11px] font-mono text-slate-500 bg-slate-100 px-2 py-0.5 rounded">
            <Clock className="w-3 h-3 text-slate-400" />
            <span>{durationMs}ms</span>
          </div>
        )}
      </div>

      {/* Table Area */}
      {rows.length === 0 ? (
        <div className="p-8 text-center text-xs text-slate-500">
          Query executed successfully, but returned 0 matching records.
        </div>
      ) : (
        <div tabIndex={0} role="region" aria-label="Query results table" className="overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-100/75 border-b border-slate-200 text-slate-700 font-semibold uppercase tracking-wider text-[11px]">
                {columns.map((col, idx) => (
                  <th key={idx} className="px-3.5 py-2.5 whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
              {currentRows.map((row, rIdx) => (
                <tr
                  key={rIdx}
                  className={rIdx % 2 === 0 ? 'bg-white hover:bg-slate-50/80' : 'bg-slate-50/40 hover:bg-slate-50/80'}
                >
                  {columns.map((col, cIdx) => {
                    const val = row[col];
                    const isNull = val === null || val === undefined;
                    return (
                      <td key={cIdx} className="px-3.5 py-2 whitespace-nowrap text-slate-700">
                        {isNull ? (
                          <span className="text-slate-400 italic font-sans text-[10px]">null</span>
                        ) : typeof val === 'boolean' ? (
                          <span className={val ? 'text-emerald-600 font-semibold' : 'text-rose-600 font-semibold'}>
                            {String(val)}
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
      )}

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="bg-slate-50/80 px-4 py-2 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500">
          <span>
            Showing {startIndex + 1}–{Math.min(startIndex + pageSize, totalRows)} of {totalRows}
          </span>
          <div className="flex items-center space-x-1.5">
            <button
              onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
              disabled={currentPage === 1}
              className="p-1 rounded hover:bg-slate-200 disabled:opacity-40 disabled:hover:bg-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="font-mono text-xs px-1">
              {currentPage} / {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
              disabled={currentPage === totalPages}
              className="p-1 rounded hover:bg-slate-200 disabled:opacity-40 disabled:hover:bg-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
              aria-label="Next page"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
