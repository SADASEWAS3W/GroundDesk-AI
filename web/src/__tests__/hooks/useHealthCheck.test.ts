import { act, renderHook, waitFor } from "@testing-library/react";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  checkHealth: vi.fn(),
}));

const mockedCheckHealth = vi.mocked(api.checkHealth);

describe("useHealthCheck", () => {
  beforeEach(() => {
    mockedCheckHealth.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("starts with null while the initial check is pending", () => {
    mockedCheckHealth.mockReturnValue(new Promise(() => undefined));

    const { result } = renderHook(() => useHealthCheck());

    expect(result.current.isHealthy).toBeNull();
  });

  it("returns true when the backend is healthy", async () => {
    mockedCheckHealth.mockResolvedValue(true);

    const { result } = renderHook(() => useHealthCheck());

    await waitFor(() => {
      expect(result.current.isHealthy).toBe(true);
    });
  });

  it("returns false when the backend is unhealthy", async () => {
    mockedCheckHealth.mockResolvedValue(false);

    const { result } = renderHook(() => useHealthCheck());

    await waitFor(() => {
      expect(result.current.isHealthy).toBe(false);
    });
  });

  it("passes an abort signal to the initial health check", async () => {
    mockedCheckHealth.mockResolvedValue(true);

    renderHook(() => useHealthCheck());

    await waitFor(() => {
      expect(mockedCheckHealth).toHaveBeenCalledTimes(1);
    });
    expect(mockedCheckHealth).toHaveBeenCalledWith(expect.any(AbortSignal));
  });

  it("aborts a health check after five seconds", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    mockedCheckHealth.mockImplementationOnce((requestSignal) => {
      signal = requestSignal;
      return new Promise((resolve) => {
        requestSignal?.addEventListener("abort", () => resolve(false));
      });
    });
    const { result } = renderHook(() => useHealthCheck());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(signal?.aborted).toBe(true);
    expect(result.current.isHealthy).toBe(false);
  });

  it("allows callers to refresh the health status", async () => {
    mockedCheckHealth
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    const { result } = renderHook(() => useHealthCheck());
    await waitFor(() => {
      expect(result.current.isHealthy).toBe(false);
    });

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.isHealthy).toBe(true);
    expect(mockedCheckHealth).toHaveBeenCalledTimes(2);
  });

  it("cancels the previous request and ignores its late result", async () => {
    const requests: Array<{
      signal: AbortSignal | undefined;
      resolve: (healthy: boolean) => void;
    }> = [];
    mockedCheckHealth.mockImplementation(
      (signal) =>
        new Promise((resolve) => {
          requests.push({ signal, resolve });
        }),
    );
    const { result } = renderHook(() => useHealthCheck());
    await waitFor(() => {
      expect(requests).toHaveLength(1);
    });

    let latestRefresh: Promise<void> | undefined;
    act(() => {
      latestRefresh = result.current.refresh();
    });
    expect(requests[0].signal?.aborted).toBe(true);
    expect(requests).toHaveLength(2);

    await act(async () => {
      requests[1].resolve(true);
      await latestRefresh;
    });
    expect(result.current.isHealthy).toBe(true);

    await act(async () => {
      requests[0].resolve(false);
      await Promise.resolve();
    });
    expect(result.current.isHealthy).toBe(true);
  });

  it("checks again when the page becomes visible", async () => {
    mockedCheckHealth.mockResolvedValue(true);
    const visibilityState = vi.spyOn(document, "visibilityState", "get");
    visibilityState.mockReturnValue("hidden");
    renderHook(() => useHealthCheck());
    await waitFor(() => {
      expect(mockedCheckHealth).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(mockedCheckHealth).toHaveBeenCalledTimes(1);

    visibilityState.mockReturnValue("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(mockedCheckHealth).toHaveBeenCalledTimes(2);
    });
  });

  it("checks again when the browser comes online", async () => {
    mockedCheckHealth.mockResolvedValue(true);
    renderHook(() => useHealthCheck());
    await waitFor(() => {
      expect(mockedCheckHealth).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      window.dispatchEvent(new Event("online"));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(mockedCheckHealth).toHaveBeenCalledTimes(2);
    });
  });

  it("aborts the current request and removes listeners on unmount", async () => {
    let signal: AbortSignal | undefined;
    mockedCheckHealth.mockImplementation((requestSignal) => {
      signal = requestSignal;
      return new Promise(() => undefined);
    });
    const { unmount } = renderHook(() => useHealthCheck());
    await waitFor(() => {
      expect(mockedCheckHealth).toHaveBeenCalledTimes(1);
    });

    unmount();
    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));

    expect(signal?.aborted).toBe(true);
    expect(mockedCheckHealth).toHaveBeenCalledTimes(1);
  });
});
