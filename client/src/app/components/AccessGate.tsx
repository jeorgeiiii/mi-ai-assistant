'use client';

import { useState, FormEvent } from 'react';

interface AccessGateProps {
  apiBaseUrl: string;
  onUnlock: (key: string) => void;
}

const DENIED_MESSAGE = 'Sorry Only Prince Mehra can use this website';

export default function AccessGate({ apiBaseUrl, onUnlock }: AccessGateProps) {
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || checking) return;

    setChecking(true);
    setError(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/threads`, {
        headers: { 'X-Access-Key': input.trim() },
      });

      if (response.ok) {
        onUnlock(input.trim());
      } else {
        setError(DENIED_MESSAGE);
      }
    } catch {
      setError('Could not reach the server. Please try again.');
    } finally {
      setChecking(false);
    }
  };

  return (
    <main className="relative flex h-screen items-center justify-center bg-gray-950 p-4">
      <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-gray-900/90 backdrop-blur-xl p-6 shadow-2xl text-center">
        <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-gray-800 flex items-center justify-center">
          <svg className="w-6 h-6 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
            />
          </svg>
        </div>
        <h1 className="text-lg font-semibold text-white mb-1">Private Assistant</h1>
        <p className="text-sm text-gray-400 mb-4">Enter the access password to continue.</p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Password"
            className="w-full px-3 py-2 rounded-lg bg-gray-800 text-white text-sm border border-gray-700 focus:outline-none focus:border-blue-500 transition-colors"
            autoFocus
          />
          <button
            type="submit"
            disabled={checking || !input.trim()}
            className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors duration-200"
          >
            {checking ? 'Checking...' : 'Unlock'}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </div>
    </main>
  );
}
