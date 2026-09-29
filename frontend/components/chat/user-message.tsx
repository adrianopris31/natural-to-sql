"use client";

import { User } from "lucide-react";

interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="flex justify-end gap-3 my-4">
      <div className="flex max-w-[85%] sm:max-w-[75%] flex-col items-end">
        <div className="rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground shadow-xs">
          <p className="whitespace-pre-wrap break-words">{content}</p>
        </div>
      </div>
      <div className="flex size-8 shrink-0 select-none items-center justify-center rounded-full bg-primary/10 text-primary">
        <User className="size-4" />
      </div>
    </div>
  );
}
