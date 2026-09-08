"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_DURATION_MS = 10000; // 默认冷却时间
const COOLDOWN_END_STORAGE_KEY = "grounddesk:cooldown-end"; // 保存在sessionStorage中的键名，保存的是冷却结束时间

function validateDuration(durationMs: number): number { // 校验冷却时长
  if (!Number.isFinite(durationMs) || durationMs < 0) {
    throw new RangeError(
      "Cooldown duration must be a finite, non-negative number.",
    );
  }
  return durationMs;
}

function readPersistedEnd(): number | null { // 读取已保存的结束时间
  try {
    const storedValue = window.sessionStorage.getItem(COOLDOWN_END_STORAGE_KEY);
    if (storedValue === null) return null;

    const endTime = Number(storedValue);
    if (!Number.isFinite(endTime) || endTime <= Date.now()) {
      window.sessionStorage.removeItem(COOLDOWN_END_STORAGE_KEY);
      return null;
    }
    return endTime;
  } catch {
    return null;
  }
}

function persistEnd(endTime: number) { // 保存结束时间
  try {
    window.sessionStorage.setItem(COOLDOWN_END_STORAGE_KEY, String(endTime));
  } catch {
    // Storage can be unavailable without preventing an in-memory cooldown.
  }
}

function clearPersistedEnd() { // 删除结束时间
  try {
    window.sessionStorage.removeItem(COOLDOWN_END_STORAGE_KEY);
  } catch {
    // Storage can be unavailable without preventing an in-memory cooldown.
  }
}

export function useCooldown(durationMs: number = DEFAULT_DURATION_MS) {
  const validatedDurationMs = validateDuration(durationMs);
  const [isCoolingDown, setIsCoolingDown] = useState(false); // 表示当前是否处于冷却期
  const [remainingSeconds, setRemainingSeconds] = useState(0); // 表示页面应显示的剩余秒数
  const endTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null); // 最终结束冷却的setTimeout
  const tickTimerRef = useRef<ReturnType<typeof setInterval> | null>(null); // 每秒刷新显示的setInterval
  const endTimeRef = useRef<number | null>(null); // 当前冷却的绝对结束时间

  const clearTimers = useCallback(() => {
    if (endTimerRef.current !== null) {
      clearTimeout(endTimerRef.current);
      endTimerRef.current = null;
    }
    if (tickTimerRef.current !== null) {
      clearInterval(tickTimerRef.current);
      tickTimerRef.current = null;
    }
  }, []);
  // 完整冷却结束
  const cancelCooldown = useCallback(() => {
    clearTimers(); // 停止计时器
    endTimeRef.current = null; // 清空内存中的结束时间
    clearPersistedEnd(); // 删除持久化结束时间
    setIsCoolingDown(false); // 将冷却状态设为false
    setRemainingSeconds(0); // 将剩余秒数归为0
  }, [clearTimers]);

  const scheduleCooldown = useCallback( // 安排一次冷却
    (endTime: number) => {
      clearTimers();
      const remainingMs = Math.max(0, endTime - Date.now());
      if (remainingMs <= 0) {
        cancelCooldown();
        return;
      }

      endTimeRef.current = endTime;
      persistEnd(endTime);
      setIsCoolingDown(true);
      setRemainingSeconds(Math.ceil(remainingMs / 1000));

      tickTimerRef.current = setInterval(() => {
        const currentEndTime = endTimeRef.current;
        if (currentEndTime === null) return;

        const currentRemainingMs = Math.max(0, currentEndTime - Date.now());
        if (currentRemainingMs <= 0) {
          cancelCooldown();
        } else {
          setRemainingSeconds(Math.ceil(currentRemainingMs / 1000));
        }
      }, 1000);

      endTimerRef.current = setTimeout(cancelCooldown, remainingMs);
    },
    [cancelCooldown, clearTimers],
  );

  const startCooldown = useCallback(() => { // 供组件开始冷却
    if (validatedDurationMs === 0) {
      cancelCooldown();
      return;
    }
    scheduleCooldown(Date.now() + validatedDurationMs); // 计算冷却结束时间
  }, [cancelCooldown, scheduleCooldown, validatedDurationMs]);

  useEffect(() => { // 挂载时恢复冷却
    const persistedEnd = readPersistedEnd();
    if (persistedEnd !== null) {
      // Restoring persisted external state intentionally synchronizes on mount.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      scheduleCooldown(persistedEnd);
    }

    return clearTimers;
  }, [clearTimers, scheduleCooldown]);

  return {
    isCoolingDown,
    remainingSeconds,
    startCooldown,
    cancelCooldown,
  };
}
