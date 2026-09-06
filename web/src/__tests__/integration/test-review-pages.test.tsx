import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReviewsPage from "@/app/reviews/page";
import ReviewDetailPage from "@/app/reviews/[runId]/page";
import * as api from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ runId: "review-1" }),
}));

vi.mock("@/lib/api", () => ({
  listReviews: vi.fn(),
  getReview: vi.fn(),
  submitReview: vi.fn(),
}));

const review = {
  run_id: "review-1",
  status: "waiting_review" as const,
  original_query: "Please refund my payment",
  draft_answer: "Billing policy [1]",
  citations: [{ index: 1, document_id: "doc-1", title: "Billing", excerpt: "Policy evidence" }],
  review_reason: "high_risk_request",
  conversation_id: null,
  ticket_id: null,
  final_answer: null,
  decision_action: null,
};

describe("review pages", () => {
  beforeEach(() => {
    vi.mocked(api.listReviews).mockReset();
    vi.mocked(api.getReview).mockReset();
    vi.mocked(api.submitReview).mockReset();
  });

  it("lists pending review records", async () => {
    vi.mocked(api.listReviews).mockResolvedValue({ reviews: [review] });
    render(<ReviewsPage />);
    expect(await screen.findByText("Please refund my payment")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/reviews/review-1",
    );
  });

  it("loads a review and submits an edited answer", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getReview)
      .mockResolvedValueOnce(review)
      .mockResolvedValueOnce({
        ...review,
        status: "completed",
        final_answer: "Updated billing answer [1]",
        decision_action: "edit",
      });
    vi.mocked(api.submitReview).mockResolvedValue({
      job_id: "review-1",
      status: "completed",
      response: "Updated billing answer [1]",
      error: null,
      retry_after: null,
    });

    render(<ReviewDetailPage />);
    const textbox = await screen.findByLabelText("Draft answer");
    fireEvent.change(textbox, { target: { value: "Updated billing answer [1]" } });
    await user.click(screen.getByRole("button", { name: "Approve edited answer" }));

    await waitFor(() => {
      expect(api.submitReview).toHaveBeenCalledWith(
        "review-1",
        "edit",
        "Updated billing answer [1]",
      );
    });
    expect(await screen.findByText(/finalized with status: completed/i)).toBeInTheDocument();
  });
});
