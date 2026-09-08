import { act, render, screen, waitFor } from "@testing-library/react";
import { SupportForm } from "@/components/SupportForm";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  submitChat: vi.fn(),
  getJobStatus: vi.fn(),
  submitReview: vi.fn(),
  checkHealth: vi.fn(),
}));

const mockedGetJobStatus = vi.mocked(api.getJobStatus);
const mockedCheckHealth = vi.mocked(api.checkHealth);

function persistConversation(messages: unknown[], isFollowUpMode = false) {
  window.sessionStorage.setItem(
    "grounddesk:conversation",
    JSON.stringify({
      messages,
      customerName: "Ali",
      customerEmail: "ali@test.com",
      isFollowUpMode,
    }),
  );
}

describe("SupportForm session recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedCheckHealth.mockResolvedValue(true);
    mockedGetJobStatus.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resumes polling for a persisted processing job", async () => {
    persistConversation([
      {
        id: "message-1",
        role: "customer",
        content: "Help",
        timestamp: new Date().toISOString(),
        status: "processing",
        jobId: "job-1",
      },
    ]);
    mockedGetJobStatus.mockResolvedValue({
      job_id: "job-1",
      status: "completed",
      response: "Recovered answer",
      error: null,
      retry_after: null,
    });

    render(<SupportForm />);
    await waitFor(() => {
      expect(screen.getByLabelText("Processing")).toBeInTheDocument();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    await waitFor(() => {
      expect(mockedGetJobStatus).toHaveBeenCalledWith(
        "job-1",
        expect.any(AbortSignal),
      );
      expect(screen.getByText("Recovered answer")).toBeInTheDocument();
    });
  });

  it("restores the review panel for a persisted draft", async () => {
    persistConversation([
      {
        id: "message-1",
        role: "customer",
        content: "Please refund me",
        timestamp: new Date().toISOString(),
        status: "completed",
        jobId: "job-review",
      },
      {
        id: "reply-1",
        role: "agent",
        content: "Draft answer",
        timestamp: new Date().toISOString(),
        status: "waiting_review",
        jobId: "job-review",
        replyToId: "message-1",
        requiresHumanReview: true,
        reviewReason: "high_risk_request",
      },
    ]);

    render(<SupportForm />);

    await waitFor(() => {
      expect(screen.getByLabelText("Human review")).toBeInTheDocument();
      expect(screen.getByLabelText("Reviewed answer")).toHaveValue(
        "Draft answer",
      );
    });
    expect(mockedGetJobStatus).not.toHaveBeenCalled();
  });
});
