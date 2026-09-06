"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getReview, submitReview } from "@/lib/api";
import type { JobStatus, ReviewDetail } from "@/lib/types";

export default function ReviewDetailPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<JobStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getReview(runId)
      .then((item) => {
        if (!cancelled) {
          setReview(item);
          setAnswer(item.draft_answer);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load review");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const decide = useCallback(async (action: "approve" | "edit" | "reject") => {
    setSubmitting(true);
    setError(null);
    try {
      const status = await submitReview(
        runId,
        action,
        action === "edit" ? answer : undefined,
      );
      setResult(status);
      const refreshed = await getReview(runId);
      setReview(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    } finally {
      setSubmitting(false);
    }
  }, [answer, runId]);

  return (
    <main className="mx-auto min-h-screen max-w-4xl px-4 py-10">
      <Link href="/reviews" className="text-sm text-blue-700 hover:underline">
        ← Pending reviews
      </Link>

      {loading && <p className="mt-6 text-sm text-gray-600">Loading review…</p>}
      {error && (
        <div className="mt-6 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}
      {review && (
        <section className="mt-6 space-y-5">
          <header>
            <p className="text-sm font-medium text-amber-700">{review.status}</p>
            <h1 className="mt-1 text-2xl font-semibold text-gray-950">Review response</h1>
            <p className="mt-2 text-gray-700">{review.original_query}</p>
            <p className="mt-1 text-sm text-gray-500">
              Reason: {review.review_reason ?? "Manual verification required"}
            </p>
          </header>

          <div>
            <label htmlFor="review-answer" className="mb-2 block text-sm font-medium text-gray-900">
              Draft answer
            </label>
            <textarea
              id="review-answer"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              disabled={review.status !== "waiting_review" || submitting}
              className="min-h-48 w-full rounded-lg border border-gray-300 p-3 text-sm"
            />
          </div>

          {review.citations.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-gray-900">Evidence</h2>
              <div className="mt-2 space-y-2">
                {review.citations.map((citation) => (
                  <details key={citation.document_id} className="rounded border border-gray-200 p-3 text-sm">
                    <summary className="cursor-pointer font-medium">
                      [{citation.index}] {citation.title}
                    </summary>
                    <p className="mt-2 text-gray-600">{citation.excerpt}</p>
                  </details>
                ))}
              </div>
            </div>
          )}

          {review.status === "waiting_review" && (
            <div className="flex flex-wrap gap-2">
              <button disabled={submitting} onClick={() => void decide("approve")} className="rounded bg-green-700 px-4 py-2 text-sm text-white disabled:opacity-50">
                Approve draft
              </button>
              <button disabled={submitting || !answer.trim()} onClick={() => void decide("edit")} className="rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:opacity-50">
                Approve edited answer
              </button>
              <button disabled={submitting} onClick={() => void decide("reject")} className="rounded bg-red-700 px-4 py-2 text-sm text-white disabled:opacity-50">
                Reject
              </button>
            </div>
          )}

          {result && (
            <p className="rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
              Review finalized with status: {result.status}
            </p>
          )}
        </section>
      )}
    </main>
  );
}
