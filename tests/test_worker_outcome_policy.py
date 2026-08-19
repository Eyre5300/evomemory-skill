from evomemory_sync.worker import _record_allowed_for_outcome


def test_successful_run_may_publish_recipe():
    assert _record_allowed_for_outcome(
        {"run_success_flag": True},
        {"memory_type": "recipe"},
    )


def test_failed_run_cannot_publish_success_shaped_recipe():
    assert not _record_allowed_for_outcome(
        {"run_success_flag": False},
        {"memory_type": "recipe"},
    )


def test_failed_run_may_publish_failed_experiment():
    assert _record_allowed_for_outcome(
        {"run_success_flag": False},
        {"memory_type": "experiment", "outcome": "failure"},
    )


def test_failed_run_cannot_publish_ideation():
    assert not _record_allowed_for_outcome(
        {"run_success_flag": False},
        {"memory_type": "ideation"},
    )


def test_failed_run_may_publish_inconclusive_experiment():
    assert _record_allowed_for_outcome(
        {"run_success_flag": False},
        {"memory_type": "experiment", "outcome": "inconclusive"},
    )


def test_applied_ideation_only_allows_experiment():
    ctx = {"run_success_flag": True, "_parent_ideation_id": "idea-id"}
    assert _record_allowed_for_outcome(ctx, {"memory_type": "experiment", "outcome": "success"})
    assert not _record_allowed_for_outcome(ctx, {"memory_type": "recipe"})


def test_applied_ideation_failed_run_rejects_success_experiment():
    ctx = {"run_success_flag": False, "_parent_ideation_id": "idea-id"}
    assert not _record_allowed_for_outcome(
        ctx, {"memory_type": "experiment", "outcome": "success"}
    )
    assert _record_allowed_for_outcome(
        ctx, {"memory_type": "experiment", "outcome": "failure"}
    )
