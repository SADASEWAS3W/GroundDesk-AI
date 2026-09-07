"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getJobStatus } from "@/lib/api";
import type { JobStatus } from "@/lib/types";

const TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
const MAX_NETWORK_RETRIES = 3;
const DEFAULT_RETRY_AFTER_MS = 5000;

export function useJobPolling(
  jobId: string | null,
  onComplete: (status: JobStatus) => void, // 任务完成调用
  onError: (error: string) => void, // 任务失败调用
  onReview?: (status: JobStatus) => void, // 需要人工审核调用
) {
  const [isPolling, setIsPolling] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // Refs to keep callbacks and state stable across setTimeout closures
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const onReviewRef = useRef(onReview);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  onCompleteRef.current = onComplete;
  onErrorRef.current = onError;
  onReviewRef.current = onReview;

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
    setIsPolling(false);
  }, []);

  useEffect(() => {
    if (!jobId) {
      setElapsed(0);
      return;
    }

    let networkFailures = 0;
    let cancelled = false;
    startTimeRef.current = Date.now();
    setIsPolling(true);
    setElapsed(0);

    // Tick elapsed counter every second
    elapsedTimerRef.current = setInterval(() => {
      const secs = Math.floor((Date.now() - startTimeRef.current) / 1000);
      setElapsed(secs);
    }, 1000);

    function schedulePoll(delayMs: number) {
      if (cancelled) return;
      timerRef.current = setTimeout(poll, delayMs);
    }

    async function poll() {
      if (cancelled) return;

      // Check timeout
      if (Date.now() - startTimeRef.current >= TIMEOUT_MS) {
        cleanup();
        onErrorRef.current("Request timed out. Please try again.");
        return;
      }

      try {
        const status = await getJobStatus(jobId!);
        networkFailures = 0; // reset on success

        if (cancelled) return;

        if (status.status === "completed") {
          cleanup();
          if (status.response?.trim()) {
            onCompleteRef.current(status);
          } else {
            onErrorRef.current("The completed request returned an empty response.");
          }
        } else if (status.status === "waiting_review") {
          cleanup();
          if (onReviewRef.current) {
            onReviewRef.current(status);
          } else {
            onErrorRef.current("This response requires human review.");
          }
        } else if (status.status === "failed") {
          cleanup();
          onErrorRef.current(
            status.error ?? "An error occurred while processing your request.",
          );
        } else if (status.status === "rejected") {
          cleanup();
          onErrorRef.current("The response was rejected during human review.");
        } else {
          // Still processing — schedule next poll
          const delay = status.retry_after
            ? status.retry_after * 1000
            : DEFAULT_RETRY_AFTER_MS;
          schedulePoll(delay);
        }
      } catch {
        networkFailures++;
        if (cancelled) return;

        if (networkFailures >= MAX_NETWORK_RETRIES) {
          cleanup();
          onErrorRef.current(
            "Network error. Please check your connection and try again.",
          );
        } else {
          // Retry after default interval
          schedulePoll(DEFAULT_RETRY_AFTER_MS);
        }
      }
    }

    // First poll after default delay
    schedulePoll(DEFAULT_RETRY_AFTER_MS);

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [jobId, cleanup]);

  return { isPolling, elapsed };
}
