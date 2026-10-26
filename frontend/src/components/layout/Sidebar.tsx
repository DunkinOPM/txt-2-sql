import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  MessageSquare,
  Database,
  History,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
} from 'lucide-react';

interface SidebarProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  onNavClick?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isCollapsed, onToggleCollapse, onNavClick }) => {
  const navItems = [
    {
      to: '/',
      label: 'Workspace',
      icon: MessageSquare,
      description: 'Conversational querying',
    },
    {
      to: '/datasets',
      label: 'Datasets',
      icon: Database,
      description: 'Upload and inspect schema',
    },
    {
      to: '/history',
      label: 'Query History',
      icon: History,
      description: 'Past turns and SQL logs',
    },
  ];

  return (
    <aside
      className={`bg-slate-900 text-slate-200 transition-all duration-200 flex flex-col justify-between shrink-0 h-screen sticky top-0 ${
        isCollapsed ? 'w-20' : 'w-64'
      }`}
    >
      <div>
        {/* Brand Header */}
        <div className="h-16 flex items-center justify-between px-4 border-b border-slate-800">
          {!isCollapsed && (
            <div className="flex items-center space-x-2">
              <span className="font-bold text-white tracking-wide text-sm uppercase">
                Ambiguity-Aware
              </span>
              <span className="bg-brand-600 text-white text-[10px] font-semibold px-1.5 py-0.5 rounded">
                v0.1
              </span>
            </div>
          )}
          <button
            onClick={onToggleCollapse}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors mx-auto focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            {isCollapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronLeft className="w-5 h-5" />}
          </button>
        </div>

        {/* Navigation Items */}
        <nav className="p-3 space-y-1.5" aria-label="Main Navigation">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={onNavClick}
              className={({ isActive }) =>
                `flex items-center px-3 py-2.5 rounded-lg text-sm font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-500 ${
                  isActive
                    ? 'bg-brand-600 text-white shadow-sm'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                } ${isCollapsed ? 'justify-center' : ''}`
              }
              title={isCollapsed ? item.label : undefined}
            >
              <item.icon className={`w-5 h-5 shrink-0 ${!isCollapsed ? 'mr-3' : ''}`} />
              {!isCollapsed && (
                <div className="flex flex-col">
                  <span>{item.label}</span>
                </div>
              )}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Security Baseline Badge Footer */}
      <div className="p-4 border-t border-slate-800">
        {!isCollapsed ? (
          <div className="bg-slate-800/80 rounded-lg p-3 text-xs text-slate-400 border border-slate-700/50">
            <div className="flex items-center text-emerald-400 font-medium mb-1">
              <ShieldCheck className="w-4 h-4 mr-1.5 shrink-0" />
              <span>Read-Only SQL Safety</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-normal">
              Least-privilege PostgreSQL role. No mutations or DDL permitted.
            </p>
          </div>
        ) : (
          <div className="flex justify-center" title="Read-Only SQL Execution Active">
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          </div>
        )}
      </div>
    </aside>
  );
};
