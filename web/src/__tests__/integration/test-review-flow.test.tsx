import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SupportForm } from "@/components/SupportForm";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  submitChat: vi.fn(),
  getJobStatus: vi.fn(),
  submitReview: vi.fn(),
  checkHealth: vi.fn(),
}));

const mockedSubmitChat = vi.mocked(api.submitChat);
const mockedGetJobStatus = vi.mocked(api.getJobStatus);
const mockedSubmitReview = vi.mocked(api.submitReview);
const mockedCheckHealth = vi.mocked(api.checkHealth);

async function submitReviewableMessage(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.type(screen.getByLabelText("Name"), "Ali");
  await user.type(screen.getByLabelText("Email"), "ali@test.com");
  await user.type(screen.getByLabelText("Message"), "Please refund me");
  await user.click(screen.getByRole("button", { name: "Send Message" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  await waitFor(() => {
    expect(screen.getAllByText("Draft answer")).toHaveLength(2);
  });
}

describe("Human review flow", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedSubmitChat.mockReset();
    mockedGetJobStatus.mockReset();
    mockedSubmitReview.mockReset();
    mockedCheckHealth.mockResolvedValue(true);
    mockedSubmitChat.mockResolvedValue({
      job_id: "job-review",
      status: "processing",
      retry_after: 5,
    });
    mockedGetJobStatus.mockResolvedValue({
      job_id: "job-review",
      status: "waiting_review",
      response: "Draft answer",
      error: null,
      retry_after: null,
      requires_human_review: true,
      review_reason: "high_risk_request",
      citations: [],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("updates the existing draft after an edited answer is approved", async () => {
    mockedSubmitReview.mockResolvedValue({
      job_id: "job-review",
      status: "completed",
      response: "Reviewed answer",
      error: null,
      retry_after: null,
      requires_human_review: false,
      citations: [],
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<SupportForm />);

    await submitReviewableMessage(user);
    expect(screen.queryByLabelText("Support message")).not.toBeInTheDocument();

    const editor = screen.getByLabelText("Reviewed answer");
    await user.clear(editor);
    await user.type(editor, "Reviewed answer");
    await user.click(screen.getByRole("button", { name: "Save edit" }));

    await waitFor(() => {
      expect(mockedSubmitReview).toHaveBeenCalledWith(
        "job-review",
        "edit",
        "Reviewed answer",
      );
      expect(screen.getByText("Reviewed answer")).toBeInTheDocument();
    });
    expect(screen.queryByText("Draft answer")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Support message")).toBeInTheDocument();
  });

  it("removes the draft content when a reviewer rejects it", async () => {
    mockedSubmitReview.mockResolvedValue({
      job_id: "job-review",
      status: "rejected",
      response: "",
      error: null,
      retry_after: null,
      requires_human_review: false,
      citations: [],
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<SupportForm />);

    await submitReviewableMessage(user);
    await user.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() => {
      expect(screen.getByText("Response rejected by the human reviewer."))
        .toBeInTheDocument();
    });
    expect(screen.queryByText("Draft answer")).not.toBeInTheDocument();
  });

  it("prevents duplicate review submissions while one is pending", async () => {
    let resolveReview!: (status: Awaited<ReturnType<typeof api.submitReview>>) => void;
    mockedSubmitReview.mockImplementation(
      () => new Promise((resolve) => {
        resolveReview = resolve;
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<SupportForm />);

    await submitReviewableMessage(user);
    await user.click(screen.getByRole("button", { name: "Approve" }));

    const submittingButton = screen.getByRole("button", {
      name: "Submitting...",
    });
    expect(submittingButton).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    await user.click(submittingButton);
    expect(mockedSubmitReview).toHaveBeenCalledTimes(1);

    resolveReview({
      job_id: "job-review",
      status: "completed",
      response: "Approved answer",
      error: null,
      retry_after: null,
      requires_human_review: false,
      citations: [],
    });
    await waitFor(() => {
      expect(screen.getByText("Approved answer")).toBeInTheDocument();
    });
  });

  it("retries the failed review action instead of resubmitting the chat", async () => {
    mockedSubmitReview
      .mockRejectedValueOnce(new Error("Review network error"))
      .mockResolvedValueOnce({
        job_id: "job-review",
        status: "completed",
        response: "Approved after retry",
        error: null,
        retry_after: null,
        requires_human_review: false,
        citations: [],
      });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<SupportForm />);

    await submitReviewableMessage(user);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(screen.getByText("Review network error")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Try Again" }));

    await waitFor(() => {
      expect(mockedSubmitReview).toHaveBeenCalledTimes(2);
      expect(screen.getByText("Approved after retry")).toBeInTheDocument();
    });
    expect(mockedSubmitChat).toHaveBeenCalledTimes(1);
  });
});
