"use client";

import { useCallback, useEffect, useState } from "react";
import type { Citation, Conversation, JobStatus, Message } from "@/lib/types";

const CONVERSATION_STORAGE_KEY = "grounddesk:conversation";
const MESSAGE_STATUSES = new Set<Message["status"]>([
  "sent",
  "processing",
  "waiting_review",
  "completed",
  "failed",
  "rejected",
]);

const initialConversation: Conversation = {
  messages: [],
  customerName: "", // 客户名字
  customerEmail: "", // 客户邮箱
  isFollowUpMode: false, // 是否已完成第一轮问答，决定初始表单还是追问输入框
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseCitation(value: unknown): Citation | null {
  if (
    !isRecord(value) ||
    typeof value.index !== "number" ||
    typeof value.document_id !== "string" ||
    typeof value.title !== "string" ||
    typeof value.excerpt !== "string"
  ) {
    return null;
  }
  return {
    index: value.index,
    document_id: value.document_id,
    title: value.title,
    excerpt: value.excerpt,
  };
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function parseMessage(value: unknown): Message | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    (value.role !== "customer" && value.role !== "agent") ||
    typeof value.content !== "string" ||
    typeof value.timestamp !== "string" ||
    typeof value.status !== "string" ||
    !MESSAGE_STATUSES.has(value.status as Message["status"])
  ) {
    return null;
  }

  const timestamp = new Date(value.timestamp);
  if (Number.isNaN(timestamp.getTime())) return null;

  const jobId = optionalString(value.jobId);
  const interruptedWithoutJob =
    (value.status === "sent" || value.status === "processing") && !jobId;
  const citations = Array.isArray(value.citations)
    ? value.citations.map(parseCitation).filter((item): item is Citation => item !== null)
    : undefined;

  return {
    id: value.id,
    role: value.role,
    content: value.content,
    timestamp,
    status: interruptedWithoutJob
      ? "failed"
      : (value.status as Message["status"]),
    jobId,
    replyToId: optionalString(value.replyToId),
    error: interruptedWithoutJob
      ? "The request was interrupted before a job was created. Please try again."
      : optionalString(value.error),
    citations,
    requiresHumanReview:
      typeof value.requiresHumanReview === "boolean"
        ? value.requiresHumanReview
        : undefined,
    reviewReason:
      value.reviewReason === null ? null : optionalString(value.reviewReason),
  };
}

function readPersistedConversation(): Conversation | null {
  try {
    const raw = window.sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (
      !isRecord(value) ||
      !Array.isArray(value.messages) ||
      typeof value.customerName !== "string" ||
      typeof value.customerEmail !== "string" ||
      typeof value.isFollowUpMode !== "boolean"
    ) {
      window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
      return null;
    }
    const messages = value.messages.map(parseMessage);
    if (messages.some((message) => message === null)) {
      window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
      return null;
    }
    return {
      messages: messages as Message[],
      customerName: value.customerName,
      customerEmail: value.customerEmail,
      isFollowUpMode: value.isFollowUpMode,
    };
  } catch {
    try {
      window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
    } catch {
      // Storage can be unavailable; the in-memory conversation still works.
    }
    return null;
  }
}

function persistConversation(conversation: Conversation): void {
  try {
    if (
      conversation.messages.length === 0 &&
      !conversation.customerName &&
      !conversation.customerEmail
    ) {
      window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(
      CONVERSATION_STORAGE_KEY,
      JSON.stringify(conversation),
    );
  } catch {
    // Storage can be unavailable; the in-memory conversation still works.
  }
}

export function useConversation() {
  const [conversation, setConversation] =
    useState<Conversation>(initialConversation);
  const [isHydrated, setIsHydrated] = useState(false);

  useEffect(() => {
    const restored = readPersistedConversation();
    if (restored) {
      // Restoring persisted external state intentionally synchronizes on mount.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConversation(restored);
    }
    setIsHydrated(true);
  }, []);

  useEffect(() => {
    if (!isHydrated) return;
    persistConversation(conversation);
  }, [conversation, isHydrated]);

  const addCustomerMessage = useCallback((content: string): Message => {
    const message: Message = {
      id: crypto.randomUUID(), // 浏览器生成的UUID
      role: "customer",
      content, // 客户输入的内容
      timestamp: new Date(), // 记录时间
      status: "sent", // 初始状态为sent
    };

    setConversation((prev) => ({
      ...prev,
      messages: [...prev.messages, message], // 通过不可变更新，把新消息追加到数组末尾
    }));

    return message;
  }, []);

  const updateMessageStatus = useCallback(
    (
      id: string, // 要处理的客户消息ID
      status: Message["status"], // 新状态
      response?: string, // 后端生成的客服答案
      error?: string, // 失败原因
      result?: JobStatus, // 完整任务结果，包括任务ID、引用和审核信息
    ) => {
      const responseContent = response?.trim(); // 删除回答首尾的空白字符
      const replyId = responseContent ? crypto.randomUUID() : undefined;
      const replyTimestamp = responseContent ? new Date() : undefined;

      setConversation((prev) => {
        const customerMessage = prev.messages.find(
          (message) => message.id === id && message.role === "customer",
        );
        if (!customerMessage) return prev;

        const isWaitingReview = result?.status === "waiting_review";
        const jobId = result?.job_id ?? customerMessage.jobId;
        const messages = prev.messages.map((message) =>
          message.id === id
            ? { ...message, status, error, jobId }
            : message,
        );

        // Upsert the reply so repeated completion callbacks stay idempotent.
        if (status === "completed" && responseContent) {
          const agentMessage: Message = {
            id: replyId!,
            role: "agent",
            content: responseContent,
            timestamp: replyTimestamp!,
            status: isWaitingReview ? "waiting_review" : "completed",
            jobId,
            replyToId: id,
            citations: result?.citations, // 引用
            requiresHumanReview: result?.requires_human_review, // 人工审核标记
            reviewReason: result?.review_reason, // 审核原因
          };
          // 先查找是否有已有回复
          const existingReplyIndex = messages.findIndex(
            (message) => message.role === "agent" && message.replyToId === id,
          );
          if (existingReplyIndex >= 0) {
            messages[existingReplyIndex] = {
              ...messages[existingReplyIndex],
              ...agentMessage,
              id: messages[existingReplyIndex].id,
              timestamp: messages[existingReplyIndex].timestamp,
            };
          } else {
            messages.push(agentMessage);
          }
        }

        const hasFinalResponse =
          status === "completed" && Boolean(responseContent) && !isWaitingReview;
        return {
          ...prev,
          messages,
          isFollowUpMode: prev.isFollowUpMode || hasFinalResponse,
        };
      });
    },
    [],
  );

  const setMessageJobId = useCallback((id: string, jobId: string) => {
    setConversation((prev) => {
      if (!prev.messages.some((message) => message.id === id)) return prev;
      return {
        ...prev,
        messages: prev.messages.map((message) =>
          message.id === id ? { ...message, jobId } : message,
        ),
      };
    });
  }, []);

  const applyReviewResult = useCallback((result: JobStatus) => {
    if (result.status !== "completed" && result.status !== "rejected") return;

    setConversation((prev) => {
      const replyIndex = prev.messages.findIndex(
        (message) =>
          message.role === "agent" && message.jobId === result.job_id,
      );
      if (replyIndex < 0) return prev;

      const existingReply = prev.messages[replyIndex];
      const messages = [...prev.messages];
      messages[replyIndex] = {
        ...existingReply,
        content:
          result.status === "rejected"
            ? ""
            : result.response?.trim() || existingReply.content,
        status: result.status,
        citations: result.citations,
        requiresHumanReview: false,
        reviewReason: result.review_reason,
      };

      return {
        ...prev,
        messages,
        isFollowUpMode: true,
      };
    });
  }, []);

  // 保存首次提交的客户资料
  const setCustomerInfo = useCallback((name: string, email: string) => {
    setConversation((prev) => ({
      ...prev,
      customerName: name,
      customerEmail: email,
    }));
  }, []);

  return {
    conversation, // 当前完整对话
    isHydrated,
    addCustomerMessage, // 创建本地客户信息
    updateMessageStatus, // 更新客户信息或更新Agent回复
    setMessageJobId, // 将前端信息关联到后台任务
    applyReviewResult, // 将审核状态更新回原Agent回复
    setCustomerInfo, // 保存客户身份
  };
}
