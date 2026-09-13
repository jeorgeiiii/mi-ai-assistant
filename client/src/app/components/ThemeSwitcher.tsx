'use client';

import { useState } from 'react';
import { THEMES, withParams } from '@/app/themes';

interface ThemeSwitcherProps {
  currentThemeId: string;
  onSelect: (id: string) => void;
}

export default function ThemeSwitcher({ currentThemeId, onSelect }: ThemeSwitcherProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end">
      {open && (
        <div className="mb-3 w-60 rounded-2xl border border-white/20 bg-gray-900/80 backdrop-blur-xl p-3 shadow-2xl animate-[fadeIn_0.15s_ease-out]">
          <p className="text-xs font-semibold text-gray-300 mb-2 px-1">Choose a theme</p>
          <div className="grid grid-cols-3 gap-2">
            {THEMES.map((theme) => (
              <button
                key={theme.id}
                onClick={() => {
                  onSelect(theme.id);
                  setOpen(false);
                }}
                title={theme.name}
                className={`relative h-16 rounded-xl overflow-hidden border-2 transition-all duration-200 ${
                  currentThemeId === theme.id ? 'border-white scale-105' : 'border-transparent hover:border-white/50'
                }`}
              >
                <div
                  className="absolute inset-0 bg-cover bg-center"
                  style={{ backgroundImage: `url(${withParams(theme.images[0], 200, 60)})` }}
                />
                <div className="absolute inset-0 bg-black/25" />
                <span className="absolute bottom-1 left-1 right-1 text-[10px] font-medium text-white drop-shadow text-center truncate">
                  {theme.name}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      <button
        onClick={() => setOpen((prev) => !prev)}
        title="Change theme"
        className="w-12 h-12 rounded-full text-white shadow-xl flex items-center justify-center hover:scale-105 active:scale-95 transition-transform duration-200 bg-[var(--accent)]"
      >
        <svg className="w-5 h-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c1.1 0 2-.9 2-2 0-.5-.2-.95-.5-1.29-.28-.32-.46-.74-.46-1.21 0-1.1.9-2 2-2h2c3.31 0 6-2.69 6-6 0-4.42-4.48-8-10-8z"
            fill="currentColor"
            fillOpacity="0.2"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <circle cx="6.5" cy="11.5" r="1.5" fill="currentColor" />
          <circle cx="9.5" cy="7.5" r="1.5" fill="currentColor" />
          <circle cx="14.5" cy="7.5" r="1.5" fill="currentColor" />
          <circle cx="17.5" cy="11.5" r="1.5" fill="currentColor" />
        </svg>
      </button>
    </div>
  );
}
