"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJobStatus } from "@/lib/api";
import type { JobStatus } from "@/lib/types";

const TIMEOUT_MS = 5 * 60 * 1000; // 整个任务最多轮询5分钟
const REQUEST_TIMEOUT_MS = 15 * 1000; // 每次getJobStatus请求最多等待15秒
const MAX_NETWORK_RETRIES = 3; // 连续三次请求异常后结束
const DEFAULT_RETRY_AFTER_MS = 5000; // 首次查询和默认查询间隔是5秒
const MAX_RETRY_DELAY_MS = 30 * 1000; // 指数退避最多不超过30秒，为以后增加重试次数保留
const TIMEOUT_ERROR = "Request timed out. Please try again.";
const NETWORK_ERROR = "Network error. Please check your connection and try again.";

function isRetryableError(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("status" in error)) {
    return true;
  }

  const status = (error as { status?: unknown }).status;
  if (typeof status !== "number") return true;
  return status === 408 || status === 429 || status >= 500;
}

function retryDelay(networkFailures: number): number {
  return Math.min(
    DEFAULT_RETRY_AFTER_MS * 2 ** (networkFailures - 1),
    MAX_RETRY_DELAY_MS,
  );
}

export function useJobPolling(
  jobId: string | null, // 当前需要查询的任务ID，为null时不查询
  onComplete: (status: JobStatus) => void, // 任务成功并且回答非空时调用
  onError: (error: string) => void, // 超时、网络错误、任务失败等情况调用
  onReview?: (status: JobStatus) => void, // 任务进入waiting_review时调用
) {
  const [isPolling, setIsPolling] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const onReviewRef = useRef(onReview);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deadlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);
  const startTimeRef = useRef(0);

  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
    onReviewRef.current = onReview;
  }, [onComplete, onError, onReview]);

  const cleanup = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current); // 下一次轮询定时器
      timerRef.current = null;
    }
    if (deadlineTimerRef.current !== null) {
      clearTimeout(deadlineTimerRef.current); // 整体五分钟截止定时器
      deadlineTimerRef.current = null;
    }
    if (requestTimerRef.current !== null) {
      clearTimeout(requestTimerRef.current); // 单次请求十五秒定时器
      requestTimerRef.current = null;
    }
    if (elapsedTimerRef.current !== null) {
      clearInterval(elapsedTimerRef.current); // 每秒更新elapsed的interval
      elapsedTimerRef.current = null;
    }
    requestControllerRef.current?.abort();
    requestControllerRef.current = null; // 当前请求的AbortController
    setIsPolling(false);
  }, []);

  useEffect(() => {
    if (!jobId) {
      // The job identity defines a new polling lifecycle and resets its timer.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setElapsed(0);
      return;
    }

    const currentJobId = jobId;
    let networkFailures = 0;
    let stopped = false; // 当前Effect闭包里的同步标记，负责阻止迟到结果产生业务副作用
    startTimeRef.current = Date.now();
    setIsPolling(true);
    setElapsed(0);

    const stopWithError = (message: string) => {
      if (stopped) return;
      stopped = true;
      cleanup();
      onErrorRef.current(message);
    };

    const stop = () => {
      if (stopped) return false;
      stopped = true;
      cleanup();
      return true;
    };

    elapsedTimerRef.current = setInterval(() => {
      const seconds = Math.floor(
        (Date.now() - startTimeRef.current) / 1000,
      );
      setElapsed(Math.min(seconds, TIMEOUT_MS / 1000));
    }, 1000);

    deadlineTimerRef.current = setTimeout(() => {
      stopWithError(TIMEOUT_ERROR);
    }, TIMEOUT_MS);

    function schedulePoll(delayMs: number) {
      if (stopped) return;
      timerRef.current = setTimeout(poll, delayMs);
    }

    function releaseRequest(controller: AbortController) {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (requestTimerRef.current !== null) {
        clearTimeout(requestTimerRef.current);
        requestTimerRef.current = null;
      }
    }

    async function poll() {
      if (stopped) return; // 检查是否停止

      // 检查剩余时间
      const remainingMs = TIMEOUT_MS - (Date.now() - startTimeRef.current);
      if (remainingMs <= 0) {
        stopWithError(TIMEOUT_ERROR);
        return;
      }

      // 为这一次请求创建新的AbortController和十五秒计时器
      const controller = new AbortController();
      let requestTimedOut = false;
      requestControllerRef.current = controller;
      requestTimerRef.current = setTimeout(() => {
        requestTimedOut = true;
        controller.abort();
      }, Math.min(REQUEST_TIMEOUT_MS, remainingMs));

      let status: JobStatus;
      try {
        status = await getJobStatus(currentJobId, controller.signal); // 请求并处理异常
      } catch (error) { // 请求失败后
        releaseRequest(controller); // 清理本次请求的超时计时器
        if (stopped) return; // 检查任务是否已经整体停止
        // 超时、网络异常、408、429、5XX
        if (!requestTimedOut && !isRetryableError(error)) {
          stopWithError(
            error instanceof Error ? error.message : "Unable to check job status.",
          );
          return;
        }
        // 累加失败次数，未达到三次按指数退避安排下一轮
        networkFailures += 1;
        if (networkFailures >= MAX_NETWORK_RETRIES) {
          stopWithError(NETWORK_ERROR);
        } else {
          schedulePoll(retryDelay(networkFailures));
        }
        return;
      }
      // 请求成功
      releaseRequest(controller);
      if (stopped) return;
      networkFailures = 0;

      if (status.status === "completed") {
        if (!stop()) return;
        if (status.response?.trim()) {
          onCompleteRef.current(status); // 完整JobStatus传给调用方
        } else {
          onErrorRef.current("The completed request returned an empty response.");
        }
      } else if (status.status === "waiting_review") {
        if (!stop()) return;
        if (onReviewRef.current) {
          onReviewRef.current(status); // 停止轮询，把任务交给人工审核页面
        } else {
          onErrorRef.current("This response requires human review.");
        }
      } else if (status.status === "failed") {
        stopWithError(
          status.error ?? "An error occurred while processing your request.",
        );
      } else if (status.status === "rejected") {
        stopWithError("The response was rejected during human review.");
      } else {
        const delay = // processing时
          status.retry_after !== null && status.retry_after !== undefined
            ? Math.max(0, status.retry_after * 1000)
            : DEFAULT_RETRY_AFTER_MS;
        schedulePoll(delay);
      }
    }

    schedulePoll(DEFAULT_RETRY_AFTER_MS);

    return () => {
      stopped = true;
      cleanup();
    };
  }, [jobId, cleanup]);

  return {
    isPolling, // 当前是否正在轮询，供页面显示加载状态和禁用输入
    elapsed // 本轮任务已经经过的秒数，上限为300秒
  };
}
