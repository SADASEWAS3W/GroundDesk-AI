import { act, renderHook, waitFor } from "@testing-library/react";
import { useConversation } from "@/hooks/useConversation";

describe("useConversation", () => {
  it("initializes with empty conversation state", () => {
    const { result } = renderHook(() => useConversation());

    expect(result.current.conversation).toEqual({
      messages: [],
      customerName: "",
      customerEmail: "",
      isFollowUpMode: false,
    });
  });

  it("adds a customer message with correct defaults", () => {
    const { result } = renderHook(() => useConversation());

    let message: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      message = result.current.addCustomerMessage("Hello, I need help");
    });

    expect(message!.role).toBe("customer");
    expect(message!.content).toBe("Hello, I need help");
    expect(message!.status).toBe("sent");
    expect(message!.id).toBeDefined();
    expect(message!.timestamp).toBeInstanceOf(Date);

    expect(result.current.conversation.messages).toHaveLength(1);
    expect(result.current.conversation.messages[0].content).toBe(
      "Hello, I need help",
    );
  });

  it("adds multiple messages in order", () => {
    const { result } = renderHook(() => useConversation());

    act(() => {
      result.current.addCustomerMessage("First");
    });
    act(() => {
      result.current.addCustomerMessage("Second");
    });

    expect(result.current.conversation.messages).toHaveLength(2);
    expect(result.current.conversation.messages[0].content).toBe("First");
    expect(result.current.conversation.messages[1].content).toBe("Second");
  });

  it("updates message status to processing", () => {
    const { result } = renderHook(() => useConversation());

    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help me");
    });

    act(() => {
      result.current.updateMessageStatus(msg!.id, "processing");
    });

    expect(result.current.conversation.messages[0].status).toBe("processing");
  });

  it("appends agent message on completed status with response", () => {
    const { result } = renderHook(() => useConversation());

    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help me");
    });

    act(() => {
      result.current.updateMessageStatus(
        msg!.id,
        "completed",
        "Here is the answer",
      );
    });

    const messages = result.current.conversation.messages;
    expect(messages).toHaveLength(2);
    expect(messages[0].status).toBe("completed");
    expect(messages[1].role).toBe("agent");
    expect(messages[1].content).toBe("Here is the answer");
    expect(messages[1].status).toBe("completed");
  });

  it("sets isFollowUpMode to true after first completed response", () => {
    const { result } = renderHook(() => useConversation());

    expect(result.current.conversation.isFollowUpMode).toBe(false);

    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help");
    });
    act(() => {
      result.current.updateMessageStatus(msg!.id, "completed", "Answer");
    });

    expect(result.current.conversation.isFollowUpMode).toBe(true);
  });

  it("keeps isFollowUpMode true for subsequent messages", () => {
    const { result } = renderHook(() => useConversation());

    let msg1: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg1 = result.current.addCustomerMessage("First");
    });
    act(() => {
      result.current.updateMessageStatus(msg1!.id, "completed", "Reply 1");
    });

    let msg2: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg2 = result.current.addCustomerMessage("Second");
    });
    act(() => {
      result.current.updateMessageStatus(msg2!.id, "processing");
    });

    // Still true even though second message is processing
    expect(result.current.conversation.isFollowUpMode).toBe(true);
  });

  it("sets error on failed status", () => {
    const { result } = renderHook(() => useConversation());

    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help");
    });
    act(() => {
      result.current.updateMessageStatus(
        msg!.id,
        "failed",
        undefined,
        "Something went wrong",
      );
    });

    expect(result.current.conversation.messages[0].status).toBe("failed");
    expect(result.current.conversation.messages[0].error).toBe(
      "Something went wrong",
    );
  });

  it("sets customer info", () => {
    const { result } = renderHook(() => useConversation());

    act(() => {
      result.current.setCustomerInfo("Ali", "ali@test.com");
    });

    expect(result.current.conversation.customerName).toBe("Ali");
    expect(result.current.conversation.customerEmail).toBe("ali@test.com");
  });

  it("ignores updates for an unknown customer message", () => {
    const { result } = renderHook(() => useConversation());

    act(() => {
      result.current.updateMessageStatus(
        "missing",
        "completed",
        "Orphan response",
      );
    });

    expect(result.current.conversation.messages).toEqual([]);
    expect(result.current.conversation.isFollowUpMode).toBe(false);
  });

  it("upserts a reply when completion is delivered more than once", () => {
    const { result } = renderHook(() => useConversation());
    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help");
      result.current.setMessageJobId(msg!.id, "job-1");
    });

    act(() => {
      result.current.updateMessageStatus(
        msg!.id,
        "completed",
        "First answer",
        undefined,
        {
          job_id: "job-1",
          status: "completed",
          response: "First answer",
          error: null,
          retry_after: null,
        },
      );
      result.current.updateMessageStatus(
        msg!.id,
        "completed",
        "Updated answer",
        undefined,
        {
          job_id: "job-1",
          status: "completed",
          response: "Updated answer",
          error: null,
          retry_after: null,
        },
      );
    });

    expect(result.current.conversation.messages).toHaveLength(2);
    expect(result.current.conversation.messages[0].jobId).toBe("job-1");
    expect(result.current.conversation.messages[1].content).toBe(
      "Updated answer",
    );
    expect(result.current.conversation.messages[1].replyToId).toBe(msg!.id);
  });

  it("does not enter follow-up mode for an empty completion", () => {
    const { result } = renderHook(() => useConversation());
    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help");
    });
    act(() => {
      result.current.updateMessageStatus(msg!.id, "completed", "   ");
    });

    expect(result.current.conversation.messages).toHaveLength(1);
    expect(result.current.conversation.isFollowUpMode).toBe(false);
  });

  it("preserves citations from a completed job", () => {
    const { result } = renderHook(() => useConversation());
    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Help");
    });
    act(() => {
      result.current.updateMessageStatus(
        msg!.id,
        "completed",
        "Grounded answer [1]",
        undefined,
        {
          job_id: "job-citations",
          status: "completed",
          response: "Grounded answer [1]",
          error: null,
          retry_after: null,
          citations: [
            {
              index: 1,
              document_id: "doc-1",
              title: "Billing",
              excerpt: "Billing evidence",
            },
          ],
        },
      );
    });

    expect(result.current.conversation.messages[1].citations).toEqual([
      expect.objectContaining({ document_id: "doc-1" }),
    ]);
  });

  it("keeps a draft pending until the human review result arrives", () => {
    const { result } = renderHook(() => useConversation());
    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Please refund me");
    });
    act(() => {
      result.current.updateMessageStatus(
        msg!.id,
        "completed",
        "Draft answer",
        undefined,
        {
          job_id: "job-review",
          status: "waiting_review",
          response: "Draft answer",
          error: null,
          retry_after: null,
          requires_human_review: true,
          review_reason: "high_risk_request",
        },
      );
    });

    expect(result.current.conversation.messages[1].status).toBe(
      "waiting_review",
    );
    expect(result.current.conversation.isFollowUpMode).toBe(false);

    act(() => {
      result.current.applyReviewResult({
        job_id: "job-review",
        status: "completed",
        response: "Approved answer",
        error: null,
        retry_after: null,
        requires_human_review: false,
      });
    });

    expect(result.current.conversation.messages).toHaveLength(2);
    expect(result.current.conversation.messages[1]).toEqual(
      expect.objectContaining({
        content: "Approved answer",
        status: "completed",
        requiresHumanReview: false,
      }),
    );
    expect(result.current.conversation.isFollowUpMode).toBe(true);
  });

  it("replaces a rejected draft with a rejection state", () => {
    const { result } = renderHook(() => useConversation());
    let msg: ReturnType<typeof result.current.addCustomerMessage>;
    act(() => {
      msg = result.current.addCustomerMessage("Delete my account");
      result.current.updateMessageStatus(
        msg!.id,
        "completed",
        "Draft answer",
        undefined,
        {
          job_id: "job-rejected",
          status: "waiting_review",
          response: "Draft answer",
          error: null,
          retry_after: null,
          requires_human_review: true,
        },
      );
    });
    act(() => {
      result.current.applyReviewResult({
        job_id: "job-rejected",
        status: "rejected",
        response: "",
        error: null,
        retry_after: null,
      });
    });

    expect(result.current.conversation.messages[1]).toEqual(
      expect.objectContaining({ content: "", status: "rejected" }),
    );
  });

  it("restores a completed conversation from session storage", async () => {
    const first = renderHook(() => useConversation());
    let customerMessage: ReturnType<
      typeof first.result.current.addCustomerMessage
    >;

    act(() => {
      first.result.current.setCustomerInfo("Ali", "ali@test.com");
      customerMessage = first.result.current.addCustomerMessage("Help");
    });
    act(() => {
      first.result.current.updateMessageStatus(
        customerMessage!.id,
        "completed",
        "Restored answer",
      );
    });
    await waitFor(() => {
      expect(window.sessionStorage.getItem("grounddesk:conversation")).not.toBeNull();
    });
    first.unmount();

    const second = renderHook(() => useConversation());
    await waitFor(() => {
      expect(second.result.current.isHydrated).toBe(true);
      expect(second.result.current.conversation.messages).toHaveLength(2);
    });

    expect(second.result.current.conversation.customerName).toBe("Ali");
    expect(second.result.current.conversation.messages[0].timestamp).toBeInstanceOf(
      Date,
    );
    expect(second.result.current.conversation.messages[1].content).toBe(
      "Restored answer",
    );
  });

  it("marks an interrupted request without a job as failed after restoration", async () => {
    window.sessionStorage.setItem(
      "grounddesk:conversation",
      JSON.stringify({
        messages: [
          {
            id: "message-1",
            role: "customer",
            content: "Help",
            timestamp: new Date().toISOString(),
            status: "processing",
          },
        ],
        customerName: "Ali",
        customerEmail: "ali@test.com",
        isFollowUpMode: false,
      }),
    );

    const { result } = renderHook(() => useConversation());
    await waitFor(() => expect(result.current.isHydrated).toBe(true));

    expect(result.current.conversation.messages[0]).toEqual(
      expect.objectContaining({
        status: "failed",
        error: expect.stringContaining("interrupted"),
      }),
    );
  });

  it("discards malformed persisted conversation data", async () => {
    window.sessionStorage.setItem("grounddesk:conversation", "not-json");

    const { result } = renderHook(() => useConversation());
    await waitFor(() => expect(result.current.isHydrated).toBe(true));

    expect(result.current.conversation.messages).toEqual([]);
    expect(window.sessionStorage.getItem("grounddesk:conversation")).toBeNull();
  });
});
