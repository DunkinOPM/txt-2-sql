import React, { useEffect, useState } from 'react';
import { Sparkles, HelpCircle, Loader2 } from 'lucide-react';
import { apiClient } from '../../api/client';

interface SuggestedQuestionsProps {
  datasetId: string;
  datasetName: string;
  onSelectQuestion: (question: string) => void;
  disabled?: boolean;
}

export const SuggestedQuestions: React.FC<SuggestedQuestionsProps> = ({
  datasetId,
  datasetName,
  onSelectQuestion,
  disabled = false,
}) => {
  const [questions, setQuestions] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);

    apiClient
      .getSuggestedQuestions(datasetId)
      .then((res) => {
        if (isMounted) setQuestions(res.questions);
      })
      .catch(() => {
        if (isMounted) {
          // Fallback question if endpoint has issues
          setQuestions([`How many records are in ${datasetName}?`]);
        }
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [datasetId, datasetName]);

  if (loading) {
    return (
      <div className="flex items-center space-x-2 text-xs text-slate-400 py-1">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-500" />
        <span>Generating schema-grounded question ideas...</span>
      </div>
    );
  }

  if (questions.length === 0) return null;

  return (
    <div className="space-y-2 pt-2">
      <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
        <Sparkles className="w-3.5 h-3.5 text-amber-500" />
        <span>Suggested Questions</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {questions.map((q, idx) => (
          <button
            key={idx}
            type="button"
            disabled={disabled}
            onClick={() => onSelectQuestion(q)}
            className="inline-flex items-center text-xs font-medium px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-700 hover:border-brand-300 hover:bg-brand-50/50 hover:text-brand-700 shadow-2xs transition-all disabled:opacity-50 text-left"
          >
            <HelpCircle className="w-3 h-3 mr-1.5 text-brand-500 shrink-0" />
            <span>{q}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
