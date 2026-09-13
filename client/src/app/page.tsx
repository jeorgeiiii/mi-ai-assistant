'use client';

import { useState, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';
import Sidebar, { Thread } from '@/app/components/SideBar';
import ChatInterface, { Message, ImageAttachment } from '@/app/components/ChatInterface';
import BackgroundSlideshow from '@/app/components/BackgroundSlideshow';
import ThemeSwitcher from '@/app/components/ThemeSwitcher';
import AccessGate from '@/app/components/AccessGate';
import { DEFAULT_THEME_ID, getTheme } from '@/app/themes';
import { apiFetch, getStoredAccessKey, storeAccessKey, setAccessDeniedHandler } from '@/app/apiClient';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:5001';
const THEME_STORAGE_KEY = 'assistant-theme-id';

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [themeId, setThemeId] = useState<string>(DEFAULT_THEME_ID);
  const [locked, setLocked] = useState(true);
  const [checkingAccess, setCheckingAccess] = useState(true);
  const theme = getTheme(themeId);

  useEffect(() => {
    setAccessDeniedHandler(() => setLocked(true));

    const verifyStoredKey = async () => {
      const key = getStoredAccessKey();
      if (!key) {
        setLocked(true);
        setCheckingAccess(false);
        return;
      }
      try {
        const response = await fetch(`${API_BASE_URL}/api/threads`, {
          headers: { 'X-Access-Key': key },
        });
        setLocked(!response.ok);
      } catch {
        setLocked(true);
      } finally {
        setCheckingAccess(false);
      }
    };
    verifyStoredKey();
  }, []);

  const handleUnlock = (key: string) => {
    storeAccessKey(key);
    setLocked(false);
  };

  useEffect(() => {
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      if (saved) setThemeId(saved);
    } catch {
      // localStorage unavailable; fall back to default theme
    }
  }, []);

  const handleThemeSelect = (id: string) => {
    setThemeId(id);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, id);
    } catch {
      // ignore persistence failures (e.g. private browsing)
    }
  };

  const loadThreads = async () => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/threads`);
      const data = await response.json();
      setThreads(data.threads || []);
    } catch (error) {
      console.error("Failed to fetch threads:", error);
    }
  };

  useEffect(() => {
    if (!locked) loadThreads();
  }, [locked]);

  const startNewChat = () => {
    const newThreadId = uuidv4();
    setMessages([]);
    setCurrentThreadId(newThreadId);
    
    const newThread: Thread = { id: newThreadId, title: "New Chat" };
    setThreads((prevThreads) => [newThread, ...prevThreads]);

    handleRenameThread(newThreadId, "New Chat");
  };
  
  const handleRenameThread = async (threadId: string, newTitle: string) => {
    setThreads(threads.map(t => t.id === threadId ? { ...t, title: newTitle } : t));
    try {
      await apiFetch(`${API_BASE_URL}/api/threads/${threadId}/title`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle }),
      });
    } catch (error) {
      console.error("Failed to rename thread:", error);
    }
  };

  const handleSelectThread = async (threadId: string) => {
    setIsLoading(true);
    setCurrentThreadId(threadId);
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/history/${threadId}`);
      const data = await response.json();
      setMessages(data.messages || []);
    } catch (error) {
      console.error("Failed to fetch history:", error);
      setMessages([]);
    } finally {
      setIsLoading(false);
    }
  };

  const generateAndSetThreadTitle = async (threadId: string, message: string, reply: string) => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/generate-title`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, reply }),
      });
      const data = await response.json();
      if (data.title) {
        handleRenameThread(threadId, data.title);
      }
    } catch (error) {
      console.error("Failed to generate thread title:", error);
    }
  };

  const handleSendMessage = async (messageText: string, image?: ImageAttachment) => {
    let threadIdToUse = currentThreadId;
    const isNewThread = !threadIdToUse;

    if (isNewThread) {
      const newThreadId = uuidv4();
      setCurrentThreadId(newThreadId);
      const placeholderTitle = messageText.substring(0, 25) + (messageText.length > 25 ? '...' : '') || 'Image chat';
      const newThread: Thread = { id: newThreadId, title: placeholderTitle };

      setThreads((prev) => [newThread, ...prev]);
      threadIdToUse = newThreadId;
    }

    const userMessage: Message = { sender: 'user', text: messageText, imageUrl: image?.previewUrl };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          thread_id: threadIdToUse,
          image_base64: image?.base64,
          image_mime_type: image?.mimeType,
        }),
      });
      const data = await response.json();
      const assistantResponse: Message = { sender: 'assistant', text: data.reply };
      setMessages((prev) => [...prev, assistantResponse]);

      if (isNewThread && threadIdToUse) {
        generateAndSetThreadTitle(threadIdToUse, messageText || 'Image analysis', data.reply);
      }
    } catch (error) {
      const errorResponse: Message = { sender: 'assistant', text: "Sorry, I'm having trouble connecting." };
      setMessages((prev) => [...prev, errorResponse]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteThread = async (threadId: string) => {
    setThreads((prevThreads) => prevThreads.filter(t => t.id !== threadId));

    if (currentThreadId === threadId) {
      setCurrentThreadId(null); 
      setMessages([]);        
    }

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/threads/${threadId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        console.error("Failed to delete thread on server, rolling back UI.");
        loadThreads();
      }
      
    } catch (error) {
      console.error("Error deleting thread:", error);
      loadThreads();
    }
  };

  if (checkingAccess) {
    return <main className="h-screen bg-gray-950" />;
  }

  if (locked) {
    return <AccessGate apiBaseUrl={API_BASE_URL} onUnlock={handleUnlock} />;
  }

  return (
    <main
      className="relative flex h-screen justify-center items-center p-4"
      style={{ '--accent': theme.accent } as React.CSSProperties}
    >
      <BackgroundSlideshow images={theme.images} />
      <div
        className="flex h-[90vh] w-[90vw] max-w-6xl rounded-2xl overflow-hidden border border-white/20 backdrop-blur-2xl bg-white/10"
        style={{ boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5), 0 0 90px -20px var(--accent)' }}
      >
        <Sidebar
          threads={threads}
          activeThreadId={currentThreadId}
          onNewChat={startNewChat}
          onSelectThread={handleSelectThread}
          onRenameThread={handleRenameThread}
          onDeleteThread={handleDeleteThread}
        />
        <ChatInterface
          messages={messages}
          isLoading={isLoading}
          onSendMessage={handleSendMessage}
        />
      </div>
      <ThemeSwitcher currentThemeId={themeId} onSelect={handleThemeSelect} />
    </main>
  );
}