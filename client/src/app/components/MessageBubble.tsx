'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const AssistantAvatar = () => (
  <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center mr-3 flex-shrink-0"> 
    <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
  </div>
);

const UserAvatar = () => (
  <div className="w-8 h-8 rounded-full bg-[var(--accent)] flex items-center justify-center ml-3 flex-shrink-0">
    <span className="text-xs font-semibold text-white">PM</span>
  </div>
);

interface MessageBubbleProps {
  sender: 'user' | 'assistant';
  text: string;
  imageUrl?: string;
}

export default function MessageBubble({ sender, text, imageUrl }: MessageBubbleProps) {
  const isUser = sender === 'user';

  return (
    <div
      className={`flex items-end ${isUser ? 'justify-end' : 'justify-start'}`}
      style={{ animation: 'messageIn 0.25s ease-out' }}
    >

      {!isUser && <AssistantAvatar />}

      <div
        className={`${isUser ? 'max-w-xs md:max-w-md lg:max-w-xl' : 'max-w-xs md:max-w-lg lg:max-w-2xl'} px-4 py-3 rounded-2xl shadow-lg ${
          isUser
            ? 'bg-[var(--accent)] text-white rounded-br-none ml-3'
            : 'bg-white/90 backdrop-blur-md text-gray-800 rounded-bl-none mr-3 border border-white/60'
        }`}
      >
        {isUser ? (
          <>
            {imageUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imageUrl} alt="Attached" className="rounded-lg mb-2 max-h-52 w-full object-cover" />
            )}
            {text && <p className="text-sm break-words">{text}</p>}
          </>
        ) : (
          <div className="text-sm break-words">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
                strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
                em: ({ children }) => <em className="italic">{children}</em>,
                ul: ({ children }) => <ul className="list-disc pl-5 mb-2 last:mb-0 space-y-1">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 last:mb-0 space-y-1">{children}</ol>,
                li: ({ children }) => <li>{children}</li>,
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline break-words">
                    {children}
                  </a>
                ),
                h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-1">{children}</h1>,
                h2: ({ children }) => <h2 className="text-sm font-bold mb-2 mt-1">{children}</h2>,
                h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-1">{children}</h3>,
                blockquote: ({ children }) => (
                  <blockquote className="border-l-2 border-gray-300 pl-3 italic text-gray-600 mb-2">{children}</blockquote>
                ),
                code: ({ children }) => (
                  <code className="bg-gray-100 text-gray-800 rounded px-1 py-0.5 text-xs font-mono break-words">{children}</code>
                ),
                pre: ({ children }) => (
                  <pre className="bg-gray-100 text-gray-800 rounded p-2 mb-2 overflow-x-auto text-xs font-mono">{children}</pre>
                ),
                table: ({ children }) => (
                  <div className="overflow-x-auto mb-2 -mx-1">
                    <table className="min-w-full border-collapse text-xs">{children}</table>
                  </div>
                ),
                thead: ({ children }) => <thead className="bg-gray-50">{children}</thead>,
                th: ({ children }) => (
                  <th className="border border-gray-200 px-2 py-1 text-left font-semibold whitespace-nowrap">{children}</th>
                ),
                td: ({ children }) => <td className="border border-gray-200 px-2 py-1 align-top">{children}</td>,
                hr: () => <hr className="my-2 border-gray-200" />,
              }}
            >
              {text}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {isUser && <UserAvatar />}
      
    </div>
  );
}