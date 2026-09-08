"use client";

import { useCallback, useRef, useState } from "react";
import { useConversation } from "@/hooks/useConversation";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useJobPolling } from "@/hooks/useJobPolling";
import { useCooldown } from "@/hooks/useCooldown";
import { submitChat, submitReview } from "@/lib/api";
import type { JobStatus } from "@/lib/types";
import { InitialForm } from "./InitialForm";
import { ChatThread } from "./ChatThread";
import { CustomerHeader } from "./CustomerHeader";
import { MessageInput } from "./MessageInput";
import { StatusIndicator } from "./StatusIndicator";

const MAX_HISTORY_MESSAGES = 20;
const MAX_HISTORY_MESSAGE_LENGTH = 4000;

export function SupportForm() {
  const {
    conversation,
    addCustomerMessage,
    updateMessageStatus,
    setMessageJobId,
    applyReviewResult,
    setCustomerInfo,
  } = useConversation();
  const { isHealthy, refresh: refreshHealth } = useHealthCheck();
  const { isCoolingDown, remainingSeconds, startCooldown } = useCooldown();

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [lastSubmission, setLastSubmission] = useState<{
    name: string;
    email: string;
    message: string;
  } | null>(null);
  const [pendingReview, setPendingReview] = useState<JobStatus | null>(null);
  const [editedAnswer, setEditedAnswer] = useState("");
  const activeSubmissionRef = useRef(false);

  const handlePollComplete = useCallback(
    (status: JobStatus) => {
      if (activeMessageId) {
        updateMessageStatus(
          activeMessageId,
          "completed",
          status.response ?? undefined,
          undefined,
          status,
        );
      }
      setActiveJobId(null);
      setActiveMessageId(null);
      setIsSubmitting(false);
      setError(null);
      setLastSubmission(null);
      activeSubmissionRef.current = false;
      startCooldown();
    },
    [activeMessageId, updateMessageStatus, startCooldown],
  );

  const handlePollError = useCallback(
    (errMsg: string) => {
      if (activeMessageId) {
        updateMessageStatus(activeMessageId, "failed", undefined, errMsg);
      }
      setActiveJobId(null);
      setActiveMessageId(null);
      setIsSubmitting(false);
      setError(errMsg);
      activeSubmissionRef.current = false;
    },
    [activeMessageId, updateMessageStatus],
  );

  const handleReview = useCallback((status: JobStatus) => {
    if (activeMessageId) {
      updateMessageStatus(
        activeMessageId,
        "completed",
        status.response ?? "Waiting for human review.",
        undefined,
        status,
      );
    }
    setPendingReview(status);
    setEditedAnswer(status.response ?? "");
    setActiveJobId(null);
    setActiveMessageId(null);
    setIsSubmitting(false);
  }, [activeMessageId, updateMessageStatus]);

  const { isPolling } = useJobPolling(
    activeJobId,
    handlePollComplete,
    handlePollError,
    handleReview,
  );

  const handleReviewDecision = useCallback(async (
    action: "approve" | "edit" | "reject",
  ) => {
    if (!pendingReview) return;
    try {
      const result = await submitReview(
        pendingReview.job_id,
        action,
        action === "edit" ? editedAnswer : undefined,
      );
      if (
        result.status === "completed" &&
        !result.response?.trim()
      ) {
        throw new Error("The reviewed response was empty.");
      }
      applyReviewResult(result);
      setPendingReview(null);
      setError(null);
      setLastSubmission(null);
      activeSubmissionRef.current = false;
      startCooldown();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    }
  }, [pendingReview, editedAnswer, applyReviewResult, startCooldown]);

  const handleSubmit = useCallback(
    async (name: string, email: string, messageText: string) => {
      if (activeSubmissionRef.current) return;
      activeSubmissionRef.current = true;
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
        const completedReplyIds = new Set(
          conversation.messages
            .filter(
              (item) => item.role === "agent" && item.status === "completed",
            )
            .map((item) => item.replyToId)
            .filter((id): id is string => Boolean(id)),
        );
        const history = conversation.messages
          .filter(
            (item) =>
              item.status === "completed" &&
              (item.role === "agent" || completedReplyIds.has(item.id)),
          )
          .slice(-MAX_HISTORY_MESSAGES)
          .map((item) => ({
            role: item.role,
            content: item.content.slice(0, MAX_HISTORY_MESSAGE_LENGTH),
          }));
        const job = await submitChat({
          name,
          email,
          message: messageText,
          channel: "web",
          ...(history.length > 0 ? { history } : {}),
        });
        setMessageJobId(msg.id, job.job_id);
        setActiveJobId(job.job_id);
      } catch (err) {
        const errMsg =
          err instanceof Error ? err.message : "Failed to send message";
        updateMessageStatus(msg.id, "failed", undefined, errMsg);
        setActiveMessageId(null);
        setIsSubmitting(false);
        setError(errMsg);
        activeSubmissionRef.current = false;
      }
    },
    [
      conversation.isFollowUpMode,
      setCustomerInfo,
      addCustomerMessage,
      updateMessageStatus,
      setMessageJobId,
      conversation.messages,
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

  const isProcessing = isSubmitting || isPolling || pendingReview !== null;

  return (
    <div className="flex flex-col gap-4">
      <StatusIndicator
        isHealthy={isHealthy}
        isProcessing={isProcessing}
        error={error}
        onRetry={error ? handleRetry : undefined}
        onHealthRetry={refreshHealth}
      />

      {conversation.isFollowUpMode && (
        <CustomerHeader
          name={conversation.customerName}
          email={conversation.customerEmail}
        />
      )}

      <ChatThread messages={conversation.messages} />

      {pendingReview && (
        <section className="rounded-lg border border-amber-300 bg-amber-50 p-3" aria-label="Human review">
          <p className="text-sm font-medium text-amber-900">Human review required</p>
          <textarea
            className="mt-2 min-h-24 w-full rounded border bg-white p-2 text-sm"
            value={editedAnswer}
            onChange={(event) => setEditedAnswer(event.target.value)}
            aria-label="Reviewed answer"
          />
          <div className="mt-2 flex gap-2">
            <button onClick={() => handleReviewDecision("approve")} className="rounded bg-green-700 px-3 py-1 text-white">Approve</button>
            <button onClick={() => handleReviewDecision("edit")} className="rounded bg-blue-700 px-3 py-1 text-white">Save edit</button>
            <button onClick={() => handleReviewDecision("reject")} className="rounded bg-red-700 px-3 py-1 text-white">Reject</button>
          </div>
        </section>
      )}

      {conversation.isFollowUpMode ? (
        <MessageInput
          onSubmit={handleFollowUpSubmit}
          disabled={isProcessing || isCoolingDown}
          cooldownRemainingSeconds={isCoolingDown ? remainingSeconds : 0}
        />
      ) : (
        <InitialForm
          onSubmit={handleInitialSubmit}
          isSubmitting={isProcessing}
          isCoolingDown={isCoolingDown}
          cooldownRemainingSeconds={remainingSeconds}
        />
      )}
    </div>
  );
}
