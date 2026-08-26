"use client";

import type { Message } from "@/lib/types";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isCustomer = message.role === "customer";
  const isProcessing = message.status === "processing";
  const isFailed = message.status === "failed";

  const timestamp = new Date(message.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className={`flex ${isCustomer ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] sm:max-w-[80%] rounded-lg px-3 py-2.5 sm:px-4 sm:py-3 ${
          isCustomer
            ? "bg-blue-600 text-white"
            : "bg-gray-100 text-gray-900"
        }`}
      >
        {/* Message content */}
        {isProcessing ? (
          <div className="flex items-center gap-1" aria-label="Processing">
            <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" />
          </div>
        ) : isFailed ? (
          <p className={`text-sm ${isCustomer ? "text-red-200" : "text-red-600"}`}>
            {message.error ?? "Failed to get a response. Please try again."}
          </p>
        ) : isCustomer ? (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div>
            <div className="prose prose-sm max-w-none">
              <MarkdownRenderer content={message.content} />
            </div>
            {message.citations && message.citations.length > 0 && (
              <div className="mt-3 space-y-2" aria-label="Sources">
                {message.citations.map((citation) => (
                  <details key={citation.document_id} className="rounded border p-2 text-xs">
                    <summary className="cursor-pointer font-medium">
                      [{citation.index}] {citation.title}
                    </summary>
                    <p className="mt-1 text-gray-600">{citation.excerpt}</p>
                  </details>
                ))}
              </div>
            )}
            {message.requiresHumanReview && (
              <p className="mt-2 text-xs font-medium text-amber-700">
                Waiting for human review: {message.reviewReason ?? "verification required"}
              </p>
            )}
          </div>
        )}

        {/* Timestamp */}
        <p
          className={`mt-1 text-xs ${
            isCustomer ? "text-blue-200" : "text-gray-400"
          }`}
        >
          {timestamp}
        </p>
      </div>
    </div>
  );
}
