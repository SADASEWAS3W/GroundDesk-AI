"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { listReviews } from "@/lib/api";
import type { ReviewDetail } from "@/lib/types";

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<ReviewDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listReviews();
      setReviews(result.reviews);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load reviews");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listReviews()
      .then((result) => {
        if (!cancelled) setReviews(result.reviews);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load reviews");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto min-h-screen max-w-4xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-blue-700">GroundDesk AI</p>
          <h1 className="text-2xl font-semibold text-gray-950">Pending reviews</h1>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded border border-gray-300 px-3 py-2 text-sm"
        >
          Refresh
        </button>
      </div>

      {loading && <p className="text-sm text-gray-600">Loading reviews…</p>}
      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          <p>{error}</p>
          <button type="button" onClick={() => void load()} className="mt-2 underline">
            Try again
          </button>
        </div>
      )}
      {!loading && !error && reviews.length === 0 && (
        <p className="rounded border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
          There are no requests waiting for review.
        </p>
      )}
      <ul className="space-y-3">
        {reviews.map((review) => (
          <li key={review.run_id} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium text-gray-950">{review.original_query}</p>
                <p className="mt-1 text-sm text-amber-700">
                  {review.review_reason ?? "Manual verification required"}
                </p>
              </div>
              <Link
                href={`/reviews/${encodeURIComponent(review.run_id)}`}
                className="shrink-0 rounded bg-blue-700 px-3 py-2 text-sm text-white"
              >
                Open
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
