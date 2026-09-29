"use client";

import { Providers } from "@/components/providers";
import { ChatLayout } from "@/components/chat/chat-layout";

export default function Home() {
  return (
    <Providers>
      <ChatLayout />
    </Providers>
  );
}
