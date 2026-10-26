import React, { useState, useRef } from 'react';
import { Send, Loader2 } from 'lucide-react';

interface QueryInputProps {
  onSendMessage: (question: string) => Promise<void>;
  disabled?: boolean;
  placeholder?: string;
}

export const QueryInput: React.FC<QueryInputProps> = ({
  onSendMessage,
  disabled = false,
  placeholder = 'Ask a question about the active dataset in natural language...',
}) => {
  const [text, setText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanText = text.trim();
    if (!cleanText || disabled || submitting) return;

    setSubmitting(true);
    try {
      await onSendMessage(cleanText);
      setText('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative bg-white border border-slate-300 rounded-2xl shadow-sm focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500 transition-all">
      <textarea
        ref={textareaRef}
        aria-label="Natural language query input"
        rows={1}
        value={text}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled || submitting}
        placeholder={placeholder}
        className="w-full text-xs text-slate-900 bg-transparent px-4 py-3 pr-12 rounded-2xl resize-none focus:outline-none placeholder:text-slate-400 max-h-32 disabled:opacity-50 disabled:cursor-not-allowed"
      />
      <button aria-label="Submit query"
        type="submit"
        disabled={disabled || submitting || !text.trim()}
        className="absolute right-2.5 bottom-2.5 w-7 h-7 bg-brand-600 hover:bg-brand-700 disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-lg flex items-center justify-center transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
        title="Submit query (Enter)"
      >
        {submitting ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Send className="w-3.5 h-3.5" />
        )}
      </button>
    </form>
  );
};
