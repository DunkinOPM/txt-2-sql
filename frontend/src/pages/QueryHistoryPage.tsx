import React from 'react';
import { History, Clock } from 'lucide-react';

export const QueryHistoryPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Query History</h2>
        <p className="text-sm text-slate-500">
          Review past natural language questions, clarification turns, generated SQL, and execution metrics.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-12 text-center shadow-sm">
        <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-3 text-slate-400">
          <History className="w-6 h-6" />
        </div>
        <h3 className="text-sm font-semibold text-slate-800 mb-1">
          No queries recorded yet
        </h3>
        <p className="text-xs text-slate-500 max-w-sm mx-auto mb-4">
          Queries and multi-turn clarification sessions will be logged here once queries are submitted.
        </p>
        <span className="inline-flex items-center text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-100 text-slate-700 border border-slate-200">
          <Clock className="w-3.5 h-3.5 mr-1.5 text-brand-600" />
          Scheduled for Phase 05
        </span>
      </div>
    </div>
  );
};

