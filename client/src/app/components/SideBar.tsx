'use client';

import { useState, KeyboardEvent, MouseEvent} from 'react';

export interface Thread {
  id: string;
  title: string | null;
}

interface SidebarProps {
  threads: Thread[];
  activeThreadId: string | null;
  onNewChat: () => void;
  onSelectThread: (threadId: string) => void;
  onRenameThread: (threadId: string, newTitle: string) => Promise<void>;
  onDeleteThread: (threadId: string) => void;
}

export default function Sidebar({ threads, activeThreadId, onNewChat, onSelectThread, onRenameThread, onDeleteThread }: SidebarProps) {
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [tempTitle, setTempTitle] = useState('');
  const [deleteCandidate, setDeleteCandidate] = useState<Thread | null>(null);

  const confirmDelete = () => {
    if (deleteCandidate) {
      onDeleteThread(deleteCandidate.id);
    }
    setDeleteCandidate(null);
  };

  const handleRename = (thread: Thread) => {
    setEditingThreadId(thread.id);
    setTempTitle(thread.title || thread.id);
  };

  const handleSaveRename = async (threadId: string) => {
    if (tempTitle.trim() && tempTitle !== (threads.find(t => t.id === threadId)?.title || threadId)) {
      await onRenameThread(threadId, tempTitle.trim());
    }
    setEditingThreadId(null);
  };
  
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>, threadId: string) => {
    if (e.key === 'Enter') {
      handleSaveRename(threadId);
    } else if (e.key === 'Escape') {
      setEditingThreadId(null);
    }
  };

  return (
    <div className="w-64 text-white flex flex-col bg-gray-900/70 backdrop-blur-xl border-r border-white/10">
      <div className="p-4 border-b border-white/10">
        <button
          onClick={onNewChat}
          className="w-full bg-[var(--accent)] hover:brightness-110 text-white font-bold py-2 px-4 rounded-lg transition duration-200 shadow-md"
        >
          + New Chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        <h2 className="p-4 text-sm font-semibold text-gray-400">Previous Chats</h2>
        <ul>
          {threads.map((thread) => (
            <li key={thread.id} className="px-2 py-1 group relative">
              {editingThreadId === thread.id ? (
                <input
                  type="text"
                  value={tempTitle}
                  onChange={(e) => setTempTitle(e.target.value)}
                  onKeyDown={(e) => handleKeyDown(e, thread.id)}
                  onBlur={() => handleSaveRename(thread.id)}
                  className="w-full p-2 rounded bg-gray-600 text-white text-sm outline-none"
                  autoFocus
                />
              ) : (
                <div
                  onClick={() => onSelectThread(thread.id)}
                  className={`w-full text-left p-2 rounded truncate text-sm flex justify-between items-center cursor-pointer transition-colors duration-150 border-l-4 ${
                    activeThreadId === thread.id ? 'bg-white/10 font-medium border-[var(--accent)]' : 'border-transparent hover:bg-white/5'
                  }`}
                >
                  <span className="text-gray-300">
                    {thread.title || thread.id.substring(0, 12) + '...'}
                  </span>
  
                   <div className= "flex-shrink-0">

                   </div>
                      <button
                        onClick={(e : MouseEvent<HTMLButtonElement>) => {
                            e.stopPropagation();
                            handleRename(thread)
                          }}
                          className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-white p-1 transition-opacity duration-150"
                          title="Rename chat"
                      >
                        ✏️
                      </button>

                      <button onClick={(e : MouseEvent<HTMLButtonElement>) => {
                        e.stopPropagation();
                        setDeleteCandidate(thread);
                      }}
                      className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 p-1 transition-opacity duration-150"
                      title="Delete chat"
                      >
                        🗑️
                      </button>
                  </div>
              )}
            </li>
          ))}
        </ul>
      </div>
      <div className="p-4 border-t border-white/10">
        <p className="text-xs text-gray-500">AI Personal Assistant v1.0</p>
      </div>

      {deleteCandidate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm px-4"
          onClick={() => setDeleteCandidate(null)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-white/20 bg-gray-900/90 backdrop-blur-xl p-5 text-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold mb-2">Delete this chat?</h3>
            <p className="text-sm text-gray-300 mb-5">
              "<span className="text-gray-100 font-medium">{deleteCandidate.title || deleteCandidate.id}</span>" will be permanently deleted. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteCandidate(null)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-200 hover:bg-white/10 transition-colors duration-150"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white transition-colors duration-150"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}