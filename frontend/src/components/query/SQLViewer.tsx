import React, { useState } from 'react';
import { Copy, Check, Code2 } from 'lucide-react';

interface SQLViewerProps {
  sql: string;
}

export const SQLViewer: React.FC<SQLViewerProps> = ({ sql }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm my-3 text-xs">
      <div className="bg-slate-950/80 px-3.5 py-2 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center space-x-2 text-slate-400">
          <Code2 className="w-3.5 h-3.5 text-emerald-400" />
          <span className="font-mono text-[11px] font-medium tracking-wide uppercase text-slate-300">
            Validated PostgreSQL Query (Read-Only)
          </span>
        </div>
        <button
          onClick={handleCopy}
          type="button"
          className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
          title="Copy SQL to clipboard"
          aria-label="Copy SQL query"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3 text-emerald-400" />
              <span className="text-emerald-400">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              <span>Copy SQL</span>
            </>
          )}
        </button>
      </div>
      <div tabIndex={0} role="region" aria-label="SQL query code" className="p-3.5 overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400">
        <pre className="font-mono text-emerald-300 text-xs whitespace-pre-wrap leading-relaxed">
          {sql}
        </pre>
      </div>
    </div>
  );
};
