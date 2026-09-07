"use client";

import { useState, useCallback } from "react";
import type { Conversation, JobStatus, Message } from "@/lib/types";

const initialConversation: Conversation = {
  messages: [],
  customerName: "", // 客户名字
  customerEmail: "", // 客户邮箱
  isFollowUpMode: false, // 是否已完成第一轮问答，决定初始表单还是追问输入框
};

// 会话是只存在于当前组件生命周期里。刷新页面、组件卸载或者重新挂载以后，状态都会丢失；没有写入localStorage，也没从后端恢复
export function useConversation() {
  const [conversation, setConversation] =
    useState<Conversation>(initialConversation);

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
      id: string, // 要更新的客户消息ID
      status: Message["status"], // 新状态
      response?: string, // 后端生成的客服答案
      error?: string, // 失败原因
      result?: JobStatus, // 完整任务结果，用来提取引用和人工审核信息
    ) => {
      const responseContent = response?.trim();
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
    conversation,
    addCustomerMessage,
    updateMessageStatus,
    setMessageJobId,
    applyReviewResult,
    setCustomerInfo,
  };
}
