"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatAssistantText } from "@/lib/assistant/format-assistant-text";
import { cn } from "@/lib/utils";

type AssistantMarkdownProps = {
  content: string;
  entityHints?: string[];
  className?: string;
};

export function AssistantMarkdown({
  content,
  entityHints = [],
  className,
}: AssistantMarkdownProps) {
  const formatted = formatAssistantText(content, entityHints);

  return (
    <div className={cn("text-sm", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => (
            <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-foreground">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-foreground/90">{children}</em>
          ),
          ul: ({ children }) => (
            <ul className="mb-2 list-disc pl-4 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 list-decimal pl-4 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => <li className="mb-0.5">{children}</li>,
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-primary underline-offset-2 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              {children}
            </a>
          ),
        }}
      >
        {formatted}
      </ReactMarkdown>
    </div>
  );
}
