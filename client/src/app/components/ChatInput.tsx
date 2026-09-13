'use client';

import { useState, KeyboardEvent, useRef, ChangeEvent } from 'react';
import TextareaAutosize from 'react-textarea-autosize';
import { ImageAttachment } from './ChatInterface';

interface ChatInputProps {
  onSendMessage: (message: string, image?: ImageAttachment) => void;
  isLoading: boolean;
}

const MAX_FILE_SIZE_MB = 8;

export default function ChatInput({ onSendMessage, isLoading }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [attachedImage, setAttachedImage] = useState<ImageAttachment | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    if ((!input.trim() && !attachedImage) || isLoading) return;
    onSendMessage(input, attachedImage || undefined);
    setInput('');
    setAttachedImage(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setFileError(null);

    if (!file.type.startsWith('image/')) {
      setFileError('Please choose an image file.');
      return;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      setFileError(`Image must be under ${MAX_FILE_SIZE_MB}MB.`);
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      const [header, base64] = dataUrl.split(',');
      const mimeMatch = header.match(/data:(.*);base64/);
      const mimeType = mimeMatch ? mimeMatch[1] : file.type;
      setAttachedImage({ base64, mimeType, previewUrl: dataUrl });
    };
    reader.readAsDataURL(file);
  };

  const handleRemoveImage = () => {
    setAttachedImage(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="p-4 bg-white/40 backdrop-blur-xl border-t border-white/20">
      {fileError && (
        <p className="text-xs text-red-600 mb-2 px-1">{fileError}</p>
      )}

      {attachedImage && (
        <div className="mb-2 flex items-center gap-2">
          <div className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={attachedImage.previewUrl}
              alt="Attachment preview"
              className="h-16 w-16 object-cover rounded-lg border border-white/60 shadow-sm"
            />
            <button
              onClick={handleRemoveImage}
              className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-gray-800 text-white text-xs flex items-center justify-center shadow hover:bg-gray-900"
              title="Remove image"
            >
              ✕
            </button>
          </div>
          <span className="text-xs text-gray-600">Image attached</span>
        </div>
      )}

      <div className="flex items-end space-x-3 bg-white/80 backdrop-blur-md rounded-xl border border-white/60 p-2 shadow-md transition-colors duration-200 focus-within:border-[var(--accent)]">
        <input
          type="file"
          accept="image/*"
          ref={fileInputRef}
          onChange={handleFileChange}
          disabled={isLoading}
          hidden
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading}
          title="Attach an image"
          className="p-2 rounded-lg text-gray-500 hover:text-[var(--accent)] hover:bg-black/5 transition-colors duration-200 flex-shrink-0 disabled:opacity-40"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21.44 11.05l-9.19 9.19a5.5 5.5 0 01-7.78-7.78l9.19-9.19a3.5 3.5 0 014.95 4.95l-9.2 9.19a1.5 1.5 0 01-2.12-2.12l8.49-8.48"
            />
          </svg>
        </button>
        <TextareaAutosize
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask your assistant, or attach an image to analyze..."
          disabled={isLoading}
          rows={1}
          maxRows={5}
          className="flex-1 bg-transparent p-2 border-none resize-none focus:outline-none focus:ring-0 text-sm text-gray-800 placeholder-gray-500"
        />
        <button
          onClick={handleSend}
          disabled={isLoading || (!input.trim() && !attachedImage)}
          className={`px-4 py-2 rounded-lg transition-colors duration-200 ${
            (isLoading || (!input.trim() && !attachedImage))
              ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
              : 'bg-[var(--accent)] text-white hover:brightness-110'
          }`}
        >
          <svg className="w-5 h-5 transform rotate-90" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><path d="M10.894 2.553a1 1 0 00-1.789 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 16.571V11a1 1 0 112 0v5.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"></path></svg>
        </button>
      </div>
    </div>
  );
}
