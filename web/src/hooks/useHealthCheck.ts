"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { checkHealth } from "@/lib/api";

const HEALTH_CHECK_TIMEOUT_MS = 5000;

export function useHealthCheck() {
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null); // null, true, false三种状态，分别代表本次检查未完成、最近一次有效检查结果为健康、不健康
  const requestControllerRef = useRef<AbortController | null>(null); // 保存当前健康检查的AbortController
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null); // 保存当前请求的五秒超时定时器
  const requestSequenceRef = useRef(0); // 保存递增的请求序号，用来判断返回是否有效

  const cancelCurrentRequest = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current); // 清楚当前请求的定时器
      timeoutRef.current = null;
    }
    requestControllerRef.current?.abort(); // 取消当前网络请求
    requestControllerRef.current = null;
  }, []);

  const refresh = useCallback(async () => {
    const requestSequence = ++requestSequenceRef.current; // 生成请求序号
    cancelCurrentRequest();

    const controller = new AbortController();
    requestControllerRef.current = controller;
    timeoutRef.current = setTimeout(() => { // 五秒请求超时
      if (requestControllerRef.current === controller) {
        controller.abort();
      }
    }, HEALTH_CHECK_TIMEOUT_MS);

    let healthy = false;
    try {
      healthy = await checkHealth(controller.signal);
    } catch {
      healthy = false;
    } finally { // 请求提前完成时清除五秒定时器、清空当前请求控制器
      if (requestControllerRef.current === controller) {
        if (timeoutRef.current !== null) {
          clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
        }
        requestControllerRef.current = null;
      }
    }

    if (requestSequence === requestSequenceRef.current) {
      setIsHealthy(healthy);
    }
  }, [cancelCurrentRequest]);

  useEffect(() => {
    void refresh(); // 挂载时自动检查

    const handleVisibilityChange = () => { // 页面恢复可见时重新检查
      if (document.visibilityState === "visible") {
        void refresh();
      }
    };
    const handleOnline = () => { // 网络恢复时重新检查
      void refresh();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", handleOnline);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
      requestSequenceRef.current += 1;
      cancelCurrentRequest();
    };
  }, [cancelCurrentRequest, refresh]);

  return { isHealthy, refresh };
}
