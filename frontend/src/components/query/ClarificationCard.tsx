import React, { useState } from 'react';
import { HelpCircle, Send, Loader2, Sparkles } from 'lucide-react';

interface ClarificationCardProps {
  question: string;
  options?: string[] | null;
  onSubmitAnswer: (selectedOption?: string, freeTextAnswer?: string) => Promise<void>;
  disabled?: boolean;
}

export const ClarificationCard: React.FC<ClarificationCardProps> = ({
  question,
  options = [],
  onSubmitAnswer,
  disabled = false,
}) => {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [freeText, setFreeText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOption && !freeText.trim()) return;

    setSubmitting(true);
    try {
      await onSubmitAnswer(selectedOption || undefined, freeText.trim() || undefined);
    } finally {
      setSubmitting(false);
    }
  };

  const handleOptionClick = (opt: string) => {
    if (disabled || submitting) return;
    setSelectedOption(selectedOption === opt ? null : opt);
  };

  return (
    <div className="bg-blue-50/70 border border-blue-200 rounded-xl p-4 my-3 text-left space-y-3 shadow-sm">
      <div className="flex items-start space-x-2.5">
        <div className="w-7 h-7 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center shrink-0 mt-0.5">
          <HelpCircle className="w-4 h-4" />
        </div>
        <div className="flex-1">
          <span className="text-[10px] font-bold uppercase tracking-wider text-blue-700 block">
            Clarification Needed
          </span>
          <p className="text-xs font-semibold text-slate-900 mt-0.5">{question}</p>
        </div>
      </div>

      {/* Selectable Option Chips */}
      {options && options.length > 0 && (
        <div className="space-y-1.5 pl-9">
          <span className="text-[11px] text-slate-500 font-medium">Select a clarification option:</span>
          <div className="flex flex-wrap gap-2">
            {options.map((opt, idx) => {
              const isSelected = selectedOption === opt;
              return (
                <button aria-label={`Select option: ${opt}`}
                  key={idx}
                  type="button"
                  onClick={() => handleOptionClick(opt)}
                  disabled={disabled || submitting}
                  className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-all flex items-center space-x-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                    isSelected
                      ? 'bg-brand-600 text-white border-brand-700 shadow-sm'
                      : 'bg-white text-slate-700 border-slate-200 hover:border-brand-300 hover:bg-slate-50'
                  }`}
                >
                  <Sparkles className={`w-3 h-3 ${isSelected ? 'text-white' : 'text-brand-500'}`} />
                  <span>{opt}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Free text response / submit */}
      <form onSubmit={handleSubmit} className="pl-9 space-y-2 pt-1">
        <div className="flex items-center space-x-2">
          <input aria-label="Clarification response"
            type="text"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            disabled={disabled || submitting}
            placeholder={selectedOption ? 'Add additional notes (optional)...' : 'Or type your custom answer here...'}
            className="flex-1 text-xs border border-slate-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-brand-500 text-slate-900 placeholder:text-slate-400"
          />
          <button aria-label="Submit clarification response"
            type="submit"
            disabled={disabled || submitting || (!selectedOption && !freeText.trim())}
            className="px-3.5 py-2 bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors flex items-center space-x-1 disabled:opacity-50 disabled:cursor-not-allowed shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            {submitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <>
                <span>Clarify</span>
                <Send className="w-3 h-3" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
};
