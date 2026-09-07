"use client";

import { useState, useCallback } from "react";
import type { Conversation, JobStatus, Message } from "@/lib/types";

const initialConversation: Conversation = {
  messages: [],
  customerName: "",
  customerEmail: "",
  isFollowUpMode: false,
};

export function useConversation() {
  const [conversation, setConversation] =
    useState<Conversation>(initialConversation);

  const addCustomerMessage = useCallback((content: string): Message => {
    const message: Message = {
      id: crypto.randomUUID(),
      role: "customer",
      content,
      timestamp: new Date(),
      status: "sent",
    };

    setConversation((prev) => ({
      ...prev,
      messages: [...prev.messages, message],
    }));

    return message;
  }, []);

  const updateMessageStatus = useCallback(
    (
      id: string,
      status: Message["status"],
      response?: string,
      error?: string,
      result?: JobStatus,
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
            citations: result?.citations,
            requiresHumanReview: result?.requires_human_review,
            reviewReason: result?.review_reason,
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
