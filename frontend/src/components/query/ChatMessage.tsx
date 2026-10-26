import React from 'react';
import { User, Bot, HelpCircle, CheckCircle2 } from 'lucide-react';
import { QueryTurn } from '../../types/api';

interface ChatMessageProps {
  turn: QueryTurn;
  refinedQuestion?: string | null;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ turn, refinedQuestion }) => {
  const isUser = turn.role === 'user';
  const isClarificationAnswer = turn.turn_type === 'clarification_answer';

  return (
    <div className={`flex items-start space-x-3 ${isUser ? 'flex-row-reverse space-x-reverse' : ''}`}>
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold ${
          isUser
            ? 'bg-brand-600 text-white shadow-sm'
            : 'bg-slate-100 text-slate-700 border border-slate-200'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4 text-brand-600" />}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-xl rounded-2xl px-4 py-3 text-xs leading-relaxed shadow-sm ${
          isUser
            ? 'bg-brand-600 text-white rounded-tr-none'
            : 'bg-white text-slate-800 border border-slate-200 rounded-tl-none'
        }`}
      >
        {/* Turn type badge */}
        <div className={`flex items-center space-x-1.5 mb-1 text-[10px] uppercase font-bold tracking-wider ${isUser ? 'text-brand-100' : 'text-slate-400'}`}>
          {isClarificationAnswer ? (
            <>
              <HelpCircle className="w-3 h-3 text-brand-200" />
              <span>Clarification Response</span>
            </>
          ) : isUser ? (
            <span>Your Query</span>
          ) : (
            <span>Assistant</span>
          )}
        </div>

        {/* Content */}
        <p className="whitespace-pre-wrap font-normal">{turn.content}</p>

        {/* Refined Question note if relevant */}
        {!isUser && refinedQuestion && turn.turn_type === 'explanation' && (
          <div className="mt-2.5 pt-2 border-t border-slate-100 text-[11px] text-slate-600 bg-slate-50 p-2 rounded-lg border border-slate-200/60 flex items-start space-x-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-slate-800 block text-[10px] uppercase tracking-wider">
                Refined Unambiguous Query
              </span>
              <span className="font-mono text-slate-700">{refinedQuestion}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
