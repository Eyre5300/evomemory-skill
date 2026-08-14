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


def test_failed_run_may_publish_failed_ideation():
    assert _record_allowed_for_outcome(
        {"run_success_flag": False},
        {"memory_type": "ideation", "status": "failed"},
    )


def test_failed_run_cannot_publish_promising_ideation():
    assert not _record_allowed_for_outcome(
        {"run_success_flag": False},
        {"memory_type": "ideation", "status": "promising"},
    )
