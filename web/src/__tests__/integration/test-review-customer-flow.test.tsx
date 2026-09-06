import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SupportForm } from "@/components/SupportForm";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  submitChat: vi.fn(),
  getJobStatus: vi.fn(),
  checkHealth: vi.fn(),
}));

const mockedSubmitChat = vi.mocked(api.submitChat);
const mockedGetJobStatus = vi.mocked(api.getJobStatus);
const mockedCheckHealth = vi.mocked(api.checkHealth);

describe("customer human-review flow", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedSubmitChat.mockReset();
    mockedGetJobStatus.mockReset();
    mockedCheckHealth.mockResolvedValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("hides the internal draft and shows only the approved response", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockedSubmitChat.mockResolvedValue({
      job_id: "review-job",
      run_id: "review-job",
      status: "processing",
      retry_after: 5,
    });
    mockedGetJobStatus
      .mockResolvedValueOnce({
        job_id: "review-job",
        status: "waiting_review",
        response: null,
        error: null,
        retry_after: null,
        requires_human_review: true,
        review_reason: "high_risk_request",
      })
      .mockResolvedValueOnce({
        job_id: "review-job",
        status: "completed",
        response: "Approved final answer [1]",
        error: null,
        retry_after: null,
        citations: [{ index: 1, document_id: "doc-1", title: "Policy", excerpt: "Evidence" }],
      });

    render(<SupportForm />);
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
    await user.type(screen.getByLabelText("Name"), "Ali");
    await user.type(screen.getByLabelText("Email"), "ali@test.com");
    await user.type(screen.getByLabelText("Message"), "I need a refund");
    await user.click(screen.getByRole("button", { name: "Send Message" }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText(/waiting for human review/i)).toBeInTheDocument();
    expect(screen.queryByText("Internal draft [1]")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await waitFor(() => {
      expect(screen.getByText(/Approved final answer/)).toBeInTheDocument();
    });
    expect(screen.getByText("[1] Policy")).toBeInTheDocument();
  });

  it("continues polling when sync fallback immediately enters review", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockedSubmitChat.mockResolvedValue({
      correlation_id: "sync-review",
      run_id: "sync-review",
      conversation_id: "conversation-1",
      ticket_id: "ticket-1",
      status: "waiting_review",
      response: null,
      citations: [{ index: 1, document_id: "doc-1", title: "Policy", excerpt: "Evidence" }],
      requires_human_review: true,
      review_reason: "high_risk_request",
    });
    mockedGetJobStatus.mockResolvedValue({
      job_id: "sync-review",
      run_id: "sync-review",
      status: "completed",
      response: "Human-approved fallback answer [1]",
      error: null,
      retry_after: null,
      citations: [{ index: 1, document_id: "doc-1", title: "Policy", excerpt: "Evidence" }],
    });

    render(<SupportForm />);
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
    await user.type(screen.getByLabelText("Name"), "Ali");
    await user.type(screen.getByLabelText("Email"), "ali@test.com");
    await user.type(screen.getByLabelText("Message"), "I need a refund");
    await user.click(screen.getByRole("button", { name: "Send Message" }));

    expect(await screen.findByText(/waiting for human review/i)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(
      await screen.findByText(/Human-approved fallback answer/),
    ).toBeInTheDocument();
  });
});
