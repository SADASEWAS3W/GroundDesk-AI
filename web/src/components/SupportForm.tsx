"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
    isHydrated: isConversationHydrated,
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
    idempotencyKey: string;
  } | null>(null);
  const [pendingReview, setPendingReview] = useState<JobStatus | null>(null);
  const [editedAnswer, setEditedAnswer] = useState("");
  const [isReviewSubmitting, setIsReviewSubmitting] = useState(false);
  const [reviewAction, setReviewAction] = useState<
    "approve" | "edit" | "reject" | null
  >(null);
  const [lastReviewSubmission, setLastReviewSubmission] = useState<{
    action: "approve" | "edit" | "reject";
    answer?: string;
  } | null>(null);
  const activeSubmissionRef = useRef(false);
  const reviewSubmissionRef = useRef(false);

  useEffect(() => {
    if (
      !isConversationHydrated ||
      activeJobId ||
      pendingReview ||
      activeSubmissionRef.current
    ) {
      return;
    }

    const reviewMessage = [...conversation.messages]
      .reverse()
      .find(
        (message) =>
          message.role === "agent" &&
          message.status === "waiting_review" &&
          Boolean(message.jobId),
      );
    if (reviewMessage?.jobId) {
      activeSubmissionRef.current = true;
      setPendingReview({
        job_id: reviewMessage.jobId,
        status: "waiting_review",
        response: reviewMessage.content,
        error: null,
        retry_after: null,
        citations: reviewMessage.citations,
        requires_human_review: reviewMessage.requiresHumanReview,
        review_reason: reviewMessage.reviewReason,
      });
      setEditedAnswer(reviewMessage.content);
      return;
    }

    const processingMessage = [...conversation.messages]
      .reverse()
      .find(
        (message) =>
          message.role === "customer" &&
          message.status === "processing" &&
          Boolean(message.jobId),
      );
    if (processingMessage?.jobId) {
      activeSubmissionRef.current = true;
      setActiveMessageId(processingMessage.id);
      setActiveJobId(processingMessage.jobId);
      setIsSubmitting(true);
    }
  }, [
    activeJobId,
    conversation.messages,
    isConversationHydrated,
    pendingReview,
  ]);

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
      setLastReviewSubmission(null);
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
    setLastReviewSubmission(null);
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

  const submitReviewDecision = useCallback(
    async (
      action: "approve" | "edit" | "reject",
      answer?: string,
    ) => {
      if (!pendingReview || reviewSubmissionRef.current) return;

      const submission = { action, ...(answer !== undefined ? { answer } : {}) };
      reviewSubmissionRef.current = true;
      setIsReviewSubmitting(true);
      setReviewAction(action);
      setError(null);

      try {
        const result = await submitReview(pendingReview.job_id, action, answer);
        if (result.status === "completed" && !result.response?.trim()) {
          throw new Error("The reviewed response was empty.");
        }
        applyReviewResult(result);
        setPendingReview(null);
        setError(null);
        setLastSubmission(null);
        setLastReviewSubmission(null);
        activeSubmissionRef.current = false;
        startCooldown();
      } catch (err) {
        setLastReviewSubmission(submission);
        setError(err instanceof Error ? err.message : "Review failed");
      } finally {
        reviewSubmissionRef.current = false;
        setIsReviewSubmitting(false);
        setReviewAction(null);
      }
    },
    [pendingReview, applyReviewResult, startCooldown],
  );

  const handleReviewDecision = useCallback(
    (action: "approve" | "edit" | "reject") => {
      void submitReviewDecision(
        action,
        action === "edit" ? editedAnswer : undefined,
      );
    },
    [editedAnswer, submitReviewDecision],
  );

  const handleSubmit = useCallback(
    async (
      name: string,
      email: string,
      messageText: string,
      idempotencyKey = crypto.randomUUID(),
    ) => {
      if (activeSubmissionRef.current) return;
      activeSubmissionRef.current = true;
      setIsSubmitting(true);
      setError(null);
      setLastSubmission({ name, email, message: messageText, idempotencyKey });
      setLastReviewSubmission(null);

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
        const job = await submitChat(
          {
            name,
            email,
            message: messageText,
            channel: "web",
            ...(history.length > 0 ? { history } : {}),
          },
          idempotencyKey,
        );
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
    if (lastReviewSubmission && pendingReview) {
      void submitReviewDecision(
        lastReviewSubmission.action,
        lastReviewSubmission.answer,
      );
      return;
    }
    if (lastSubmission) {
      handleSubmit(
        lastSubmission.name,
        lastSubmission.email,
        lastSubmission.message,
        lastSubmission.idempotencyKey,
      );
    }
  }, [
    lastReviewSubmission,
    pendingReview,
    submitReviewDecision,
    lastSubmission,
    handleSubmit,
  ]);

  const isProcessing = isSubmitting || isPolling || pendingReview !== null;
  const canRetry = Boolean(
    (lastReviewSubmission && pendingReview) || lastSubmission,
  );

  return (
    <div className="flex flex-col gap-4">
      <StatusIndicator
        isHealthy={isHealthy}
        isProcessing={isProcessing}
        error={error}
        onRetry={error && canRetry ? handleRetry : undefined}
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
            disabled={isReviewSubmitting}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => handleReviewDecision("approve")}
              disabled={isReviewSubmitting}
              className="rounded bg-green-700 px-3 py-1 text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isReviewSubmitting && reviewAction === "approve"
                ? "Submitting..."
                : "Approve"}
            </button>
            <button
              type="button"
              onClick={() => handleReviewDecision("edit")}
              disabled={isReviewSubmitting}
              className="rounded bg-blue-700 px-3 py-1 text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isReviewSubmitting && reviewAction === "edit"
                ? "Submitting..."
                : "Save edit"}
            </button>
            <button
              type="button"
              onClick={() => handleReviewDecision("reject")}
              disabled={isReviewSubmitting}
              className="rounded bg-red-700 px-3 py-1 text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isReviewSubmitting && reviewAction === "reject"
                ? "Submitting..."
                : "Reject"}
            </button>
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
