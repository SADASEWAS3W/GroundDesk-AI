import { act, renderHook } from "@testing-library/react";
import { useCooldown } from "@/hooks/useCooldown";

const STORAGE_KEY = "grounddesk:cooldown-end";
const START_TIME = new Date("2026-09-08T00:00:00Z");

describe("useCooldown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START_TIME);
    window.sessionStorage.clear();
  });

  afterEach(() => {
    window.sessionStorage.clear();
    vi.useRealTimers();
  });

  it("starts inactive with no remaining time", () => {
    const { result } = renderHook(() => useCooldown(5000));

    expect(result.current.isCoolingDown).toBe(false);
    expect(result.current.remainingSeconds).toBe(0);
  });

  it("starts a cooldown and persists its end time", () => {
    const { result } = renderHook(() => useCooldown(5000));

    act(() => {
      result.current.startCooldown();
    });

    expect(result.current.isCoolingDown).toBe(true);
    expect(result.current.remainingSeconds).toBe(5);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe(
      String(START_TIME.getTime() + 5000),
    );
  });

  it("updates the remaining seconds and ends at the deadline", () => {
    const { result } = renderHook(() => useCooldown(5000));
    act(() => {
      result.current.startCooldown();
      vi.advanceTimersByTime(2000);
    });

    expect(result.current.isCoolingDown).toBe(true);
    expect(result.current.remainingSeconds).toBe(3);

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current.isCoolingDown).toBe(false);
    expect(result.current.remainingSeconds).toBe(0);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("uses the default ten-second duration", () => {
    const { result } = renderHook(() => useCooldown());
    act(() => {
      result.current.startCooldown();
      vi.advanceTimersByTime(9999);
    });

    expect(result.current.isCoolingDown).toBe(true);
    expect(result.current.remainingSeconds).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.isCoolingDown).toBe(false);
  });

  it("restarts the full duration when started again", () => {
    const { result } = renderHook(() => useCooldown(5000));
    act(() => {
      result.current.startCooldown();
      vi.advanceTimersByTime(3000);
      result.current.startCooldown();
      vi.advanceTimersByTime(3000);
    });

    expect(result.current.isCoolingDown).toBe(true);
    expect(result.current.remainingSeconds).toBe(2);

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current.isCoolingDown).toBe(false);
  });

  it("can cancel a cooldown early", () => {
    const { result } = renderHook(() => useCooldown(5000));
    act(() => {
      result.current.startCooldown();
      vi.advanceTimersByTime(1000);
      result.current.cancelCooldown();
    });

    expect(result.current.isCoolingDown).toBe(false);
    expect(result.current.remainingSeconds).toBe(0);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("clears active timers when unmounted without discarding the deadline", () => {
    const { result, unmount } = renderHook(() => useCooldown(5000));
    act(() => {
      result.current.startCooldown();
    });
    const activeTimerCount = vi.getTimerCount();
    expect(activeTimerCount).toBeGreaterThanOrEqual(2);

    unmount();

    expect(vi.getTimerCount()).toBeLessThanOrEqual(activeTimerCount - 2);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).not.toBeNull();
  });

  it("restores an active cooldown after remounting", () => {
    const first = renderHook(() => useCooldown(5000));
    act(() => {
      first.result.current.startCooldown();
      vi.advanceTimersByTime(2000);
    });
    first.unmount();

    const second = renderHook(() => useCooldown(5000));

    expect(second.result.current.isCoolingDown).toBe(true);
    expect(second.result.current.remainingSeconds).toBe(3);

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(second.result.current.isCoolingDown).toBe(false);
  });

  it("removes an expired persisted deadline", () => {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      String(START_TIME.getTime() - 1000),
    );

    const { result } = renderHook(() => useCooldown(5000));

    expect(result.current.isCoolingDown).toBe(false);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("treats a zero duration as no cooldown", () => {
    const { result } = renderHook(() => useCooldown(0));
    act(() => {
      result.current.startCooldown();
    });

    expect(result.current.isCoolingDown).toBe(false);
    expect(result.current.remainingSeconds).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects the invalid duration %s",
    (duration) => {
      expect(() => renderHook(() => useCooldown(duration))).toThrow(
        "Cooldown duration must be a finite, non-negative number.",
      );
    },
  );
});
