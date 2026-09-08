import { checkHealth, getJobStatus, submitChat } from "@/lib/api";

describe("submitChat", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the logical submission idempotency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          job_id: "job-1",
          status: "processing",
          retry_after: 5,
        }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await submitChat(
      {
        name: "Ali",
        email: "ali@test.com",
        message: "Help",
        channel: "web",
      },
      "submission-1",
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/chat",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "submission-1",
        },
      }),
    );
  });
});

describe("getJobStatus", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes the abort signal to fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          job_id: "job-1",
          status: "processing",
          response: null,
          error: null,
          retry_after: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await getJobStatus("job/1", controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs/job%2F1",
      { signal: controller.signal },
    );
  });

  it("preserves the HTTP status on API failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Job not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getJobStatus("missing")).rejects.toMatchObject({
      name: "ApiError",
      message: "Job not found",
      status: 404,
    });
  });
});

describe("checkHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes the abort signal to fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(checkHealth(controller.signal)).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/health", {
      signal: controller.signal,
    });
  });
});
