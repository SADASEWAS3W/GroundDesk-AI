from agent.review import InMemoryReviewRepository, ReviewAction, ReviewRecord, RunStatus


async def test_memory_repository_lists_only_pending_records():
    repository = InMemoryReviewRepository()
    pending = ReviewRecord(
        run_id="pending",
        original_query="Question",
        draft_answer="Draft [1]",
    )
    completed = ReviewRecord(
        run_id="completed",
        original_query="Question",
        draft_answer="Draft [1]",
    ).with_decision(
        action=ReviewAction.APPROVE,
        status=RunStatus.COMPLETED,
        final_answer="Draft [1]",
        decision_answer=None,
    )

    await repository.save(completed)
    await repository.save(pending)

    assert [record.run_id for record in await repository.list_pending()] == ["pending"]


async def test_memory_repository_returns_defensive_copy():
    repository = InMemoryReviewRepository()
    record = ReviewRecord(
        run_id="review-1",
        original_query="Question",
        draft_answer="Draft",
    )
    await repository.save(record)

    loaded = await repository.get("review-1")
    assert loaded is not None
    loaded.draft_answer = "Changed"

    reloaded = await repository.get("review-1")
    assert reloaded is not None
    assert reloaded.draft_answer == "Draft"
