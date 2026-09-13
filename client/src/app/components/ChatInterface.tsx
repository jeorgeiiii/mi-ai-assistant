'use client';

import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import { useRef, useEffect } from 'react';

export interface ImageAttachment {
  base64: string;
  mimeType: string;
  previewUrl: string;
}

export interface Message {
  sender: 'user' | 'assistant';
  text: string;
  imageUrl?: string;
}

interface ChatInterfaceProps {
  messages: Message[];
  isLoading: boolean;
  onSendMessage: (messageText: string, image?: ImageAttachment) => void;
}

export default function ChatInterface({ messages, isLoading, onSendMessage }: ChatInterfaceProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col h-full flex-1">
      <div className="p-4 border-b border-white/20 flex items-center justify-between bg-white/40 backdrop-blur-xl">
        <h1 className="text-xl font-semibold text-gray-900 drop-shadow-sm">AI Personal Assistant</h1>
        <div className={`flex items-center space-x-2 ${isLoading ? 'animate-pulse' : ''}`}>
          <div className="w-2.5 h-2.5 bg-green-500 rounded-full"></div>
          <p className="text-sm text-gray-700">{isLoading ? 'Typing...' : 'Online'}</p>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6 space-y-5 bg-white/10 backdrop-blur-sm">
        {messages.map((msg, index) => (
          <MessageBubble key={index} sender={msg.sender} text={msg.text} imageUrl={msg.imageUrl} />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <ChatInput onSendMessage={onSendMessage} isLoading={isLoading} />
    </div>
  );
}