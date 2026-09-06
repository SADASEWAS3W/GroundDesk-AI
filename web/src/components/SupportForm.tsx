"use client";

import { useCallback, useState } from "react";
import { useConversation } from "@/hooks/useConversation";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useJobPolling } from "@/hooks/useJobPolling";
import { useCooldown } from "@/hooks/useCooldown";
import { submitChat } from "@/lib/api";
import type { JobStatus } from "@/lib/types";
import { InitialForm } from "./InitialForm";
import { ChatThread } from "./ChatThread";
import { CustomerHeader } from "./CustomerHeader";
import { MessageInput } from "./MessageInput";
import { StatusIndicator } from "./StatusIndicator";

export function SupportForm() {
  const {
    conversation,
    addCustomerMessage,
    updateMessageStatus,
    setCustomerInfo,
  } = useConversation();
  const { isHealthy } = useHealthCheck();
  const { isCoolingDown, startCooldown } = useCooldown();

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [lastSubmission, setLastSubmission] = useState<{
    name: string;
    email: string;
    message: string;
  } | null>(null);
  const [waitingForReview, setWaitingForReview] = useState(false);
  const [reviewReason, setReviewReason] = useState<string | null>(null);

  const completeMessage = useCallback(
    (messageId: string, status: JobStatus) => {
      updateMessageStatus(
        messageId,
        "completed",
        status.response ?? undefined,
        undefined,
        status,
      );
      setActiveJobId(null);
      setActiveMessageId(null);
      setIsSubmitting(false);
      setError(null);
      setLastSubmission(null);
      setWaitingForReview(false);
      setReviewReason(null);
      startCooldown();
    },
    [updateMessageStatus, startCooldown],
  );

  const handlePollComplete = useCallback(
    (status: JobStatus) => {
      if (activeMessageId) completeMessage(activeMessageId, status);
    },
    [activeMessageId, completeMessage],
  );

  const handlePollError = useCallback(
    (errMsg: string) => {
      if (activeMessageId) {
        updateMessageStatus(activeMessageId, "failed", undefined, errMsg);
      }
      setActiveJobId(null);
      setActiveMessageId(null);
      setIsSubmitting(false);
      setWaitingForReview(false);
      setReviewReason(null);
      setError(errMsg);
    },
    [activeMessageId, updateMessageStatus],
  );

  const markWaitingForReview = useCallback((messageId: string, status: JobStatus) => {
    updateMessageStatus(messageId, "waiting_review");
    setIsSubmitting(false);
    setWaitingForReview(true);
    setReviewReason(status.review_reason ?? null);
  }, [updateMessageStatus]);

  const handleReview = useCallback((status: JobStatus) => {
    if (activeMessageId) markWaitingForReview(activeMessageId, status);
  }, [activeMessageId, markWaitingForReview]);

  const { isPolling } = useJobPolling(
    activeJobId,
    handlePollComplete,
    handlePollError,
    handleReview,
  );

  const handleSubmit = useCallback(
    async (name: string, email: string, messageText: string) => {
      setIsSubmitting(true);
      setError(null);
      setLastSubmission({ name, email, message: messageText });

      // Store customer info on first submission
      if (!conversation.isFollowUpMode) {
        setCustomerInfo(name, email);
      }

      // Add customer message to thread
      const msg = addCustomerMessage(messageText);
      setActiveMessageId(msg.id);
      updateMessageStatus(msg.id, "processing");

      try {
        const submission = await submitChat({
          name,
          email,
          message: messageText,
          channel: "web",
        });
        if ("job_id" in submission) {
          setActiveJobId(submission.job_id);
        } else if (submission.status === "completed" && submission.response) {
          completeMessage(msg.id, {
            job_id: submission.run_id,
            run_id: submission.run_id,
            conversation_id: submission.conversation_id,
            ticket_id: submission.ticket_id,
            status: "completed",
            response: submission.response,
            error: null,
            retry_after: null,
            citations: submission.citations,
          });
        } else if (submission.status === "waiting_review") {
          const reviewStatus: JobStatus = {
            job_id: submission.run_id,
            run_id: submission.run_id,
            conversation_id: submission.conversation_id,
            ticket_id: submission.ticket_id,
            status: "waiting_review",
            response: null,
            error: null,
            retry_after: null,
            requires_human_review: true,
            review_reason: submission.review_reason,
          };
          markWaitingForReview(msg.id, reviewStatus);
          setActiveJobId(submission.run_id);
        }
      } catch (err) {
        const errMsg =
          err instanceof Error ? err.message : "Failed to send message";
        updateMessageStatus(msg.id, "failed", undefined, errMsg);
        setActiveMessageId(null);
        setIsSubmitting(false);
        setError(errMsg);
      }
    },
    [
      conversation.isFollowUpMode,
      setCustomerInfo,
      addCustomerMessage,
      updateMessageStatus,
      completeMessage,
      markWaitingForReview,
    ],
  );

  const handleInitialSubmit = useCallback(
    (name: string, email: string, message: string) => {
      handleSubmit(name, email, message);
    },
    [handleSubmit],
  );

  const handleFollowUpSubmit = useCallback(
    (message: string) => {
      handleSubmit(
        conversation.customerName,
        conversation.customerEmail,
        message,
      );
    },
    [handleSubmit, conversation.customerName, conversation.customerEmail],
  );

  const handleRetry = useCallback(() => {
    setError(null);
    if (lastSubmission) {
      handleSubmit(
        lastSubmission.name,
        lastSubmission.email,
        lastSubmission.message,
      );
    }
  }, [lastSubmission, handleSubmit]);

  const isProcessing = isSubmitting || isPolling;

  return (
    <div className="flex flex-col gap-4">
      <StatusIndicator
        isHealthy={isHealthy}
        isProcessing={isProcessing}
        error={error}
        onRetry={error ? handleRetry : undefined}
      />

      {conversation.isFollowUpMode && (
        <CustomerHeader
          name={conversation.customerName}
          email={conversation.customerEmail}
        />
      )}

      <ChatThread messages={conversation.messages} />

      {waitingForReview && (
        <section className="rounded-lg border border-amber-300 bg-amber-50 p-3" aria-live="polite">
          <p className="text-sm font-medium text-amber-900">
            Your request is waiting for human review. The final response will appear here after approval.
            {reviewReason ? ` Review reason: ${reviewReason}.` : ""}
          </p>
        </section>
      )}

      {conversation.isFollowUpMode ? (
        <MessageInput
          onSubmit={handleFollowUpSubmit}
          disabled={isProcessing || isCoolingDown}
        />
      ) : (
        <InitialForm
          onSubmit={handleInitialSubmit}
          isSubmitting={isProcessing}
          isCoolingDown={isCoolingDown}
        />
      )}
    </div>
  );
}
