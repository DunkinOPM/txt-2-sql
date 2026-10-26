import React from 'react';
import { Database, Activity, Menu, X, LogOut, User as UserIcon } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNavigate } from 'react-router-dom';

interface TopbarProps {
  onToggleSidebar?: () => void;
  isSidebarOpen?: boolean;
}

export const Topbar: React.FC<TopbarProps> = ({ onToggleSidebar, isSidebarOpen }) => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  return (
    <header className="h-16 bg-white border-b border-slate-200 px-4 sm:px-6 flex items-center justify-between sticky top-0 z-10 shadow-xs">
      <div className="flex items-center space-x-3">
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            aria-label={isSidebarOpen ? 'Close navigation drawer' : 'Open navigation drawer'}
            className="sm:hidden p-2 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            {isSidebarOpen ? <X className="w-5 h-5" aria-hidden="true" /> : <Menu className="w-5 h-5" aria-hidden="true" />}
          </button>
        )}
        <div className="bg-brand-50 p-2 rounded-lg text-brand-600 border border-brand-100 shrink-0">
          <Database className="w-5 h-5" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-sm sm:text-base font-semibold text-slate-900 leading-tight">
            Conversational Text-to-SQL
          </h1>
          <p className="text-[11px] sm:text-xs text-slate-500">
            Ambiguity-Aware Database Exploration
          </p>
        </div>
      </div>

      <div className="flex items-center space-x-3 sm:space-x-4">
        {/* Backend Status indicator */}
        <div className="hidden sm:flex items-center text-xs text-emerald-700 bg-emerald-50 py-1.5 px-3 rounded-full border border-emerald-200 font-medium">
          <Activity className="w-3.5 h-3.5 mr-1.5 text-emerald-500" aria-hidden="true" />
          <span>Backend Connected</span>
        </div>

        {/* Authenticated User Badge & Logout */}
        {user ? (
          <div className="flex items-center space-x-2">
            <div className="flex items-center gap-1.5 text-xs text-slate-700 bg-slate-100 py-1.5 px-2.5 rounded-lg border border-slate-200">
              <UserIcon className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
              <span className="font-medium max-w-[120px] truncate" title={user.username || user.email}>
                {user.username || user.email}
              </span>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              title="Sign out"
              aria-label="Sign out"
              className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50 border border-slate-200 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-red-500"
            >
              <LogOut className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
};
