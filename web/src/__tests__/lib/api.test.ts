import { getJobStatus } from "@/lib/api";

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
