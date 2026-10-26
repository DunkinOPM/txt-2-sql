import React from 'react';
import { Loader2, CheckCircle2, HelpCircle, AlertOctagon, XCircle } from 'lucide-react';

interface QueryStatusProps {
  status: string;
  category?: string | null;
}

export const QueryStatus: React.FC<QueryStatusProps> = ({ status, category }) => {
  const getStatusBadge = () => {
    switch (status) {
      case 'classifying':
        return (
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>Classifying Intent</span>
          </span>
        );
      case 'awaiting_clarification':
        return (
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
            <HelpCircle className="w-3 h-3" />
            <span>Awaiting Clarification</span>
          </span>
        );
      case 'ready_for_sql':
      case 'generating_sql':
        return (
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            <span>Ready for SQL (Phase 4)</span>
          </span>
        );
      case 'rejected':
        return (
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle className="w-3 h-3" />
            <span>Terminated / Refused</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <AlertOctagon className="w-3 h-3" />
            <span>Failed</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-100 text-slate-700">
            {status}
          </span>
        );
    }
  };

  const getCategoryBadge = () => {
    if (!category) return null;
    let colorClass = 'bg-slate-100 text-slate-700 border-slate-200';
    if (category === 'RELEVANT_CLEAR') colorClass = 'bg-emerald-50 text-emerald-700 border-emerald-200';
    if (category === 'RELEVANT_AMBIGUOUS') colorClass = 'bg-amber-50 text-amber-700 border-amber-200';
    if (category === 'RELEVANT_UNANSWERABLE') colorClass = 'bg-orange-50 text-orange-700 border-orange-200';
    if (category === 'OUT_OF_SCOPE') colorClass = 'bg-indigo-50 text-indigo-700 border-indigo-200';
    if (category === 'NONSENSICAL') colorClass = 'bg-slate-50 text-slate-600 border-slate-200';
    if (category === 'IMPROPER_OR_UNSAFE') colorClass = 'bg-rose-50 text-rose-700 border-rose-200';

    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${colorClass}`}>
        {category}
      </span>
    );
  };

  return (
    <div className="flex items-center space-x-2">
      {getStatusBadge()}
      {getCategoryBadge()}
    </div>
  );
};
