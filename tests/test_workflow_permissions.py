from evomemory_sync.workflow_executor import WorkflowRunner, WorkflowToolSpec
from evomemory_sync.workflow_schema import EvoWorkflow, WorkflowPermissions


def _workflow(*, tools=None, permissions=None):
    return EvoWorkflow(
        title="Permission test",
        description="Verify default-deny workflow tools",
        prompts={"system": "Be safe", "user_template": "{input}"},
        tools=tools or [],
        permissions=permissions or WorkflowPermissions(),
    )


def test_remote_tool_and_local_registry_do_not_grant_execution_by_themselves():
    fn = lambda: "ok"
    workflow = _workflow(tools=["safe"], permissions=WorkflowPermissions(tools=["safe"]))
    assert WorkflowRunner(workflow, {"safe": WorkflowToolSpec(fn)}).loaded_tools == []
    assert WorkflowRunner(workflow, {"safe": fn}, approved_tools={"safe"}).loaded_tools == []


def test_declared_capability_and_local_approval_are_both_required():
    fn = lambda: "ok"
    workflow = _workflow(tools=["safe"], permissions=WorkflowPermissions(tools=["safe"]))
    runner = WorkflowRunner(
        workflow,
        {"safe": WorkflowToolSpec(fn)},
        approved_tools={"safe"},
    )
    assert runner.loaded_tools == [fn]


def test_shell_network_and_filesystem_capabilities_default_to_denied():
    fn = lambda: "danger"
    for capability in ("shell", "network", "filesystem_read", "filesystem_write"):
        workflow = _workflow(
            tools=["danger"],
            permissions=WorkflowPermissions(tools=["danger"]),
        )
        runner = WorkflowRunner(
            workflow,
            {"danger": WorkflowToolSpec(fn, frozenset({capability}))},
            approved_tools={"danger"},
        )
        assert runner.loaded_tools == []


def test_shell_requires_remote_declaration_and_local_tool_approval():
    fn = lambda: "approved"
    workflow = _workflow(
        tools=["shell"],
        permissions=WorkflowPermissions(tools=["shell"], allow_shell=True),
    )
    runner = WorkflowRunner(
        workflow,
        {"shell": WorkflowToolSpec(fn, frozenset({"shell"}))},
        approved_tools={"shell"},
    )
    assert runner.loaded_tools == [fn]


def test_tool_not_declared_in_permissions_is_rejected():
    workflow = _workflow(tools=["hidden"], permissions=WorkflowPermissions(tools=[]))
    runner = WorkflowRunner(
        workflow,
        {"hidden": WorkflowToolSpec(lambda: "no")},
        approved_tools={"hidden"},
    )
    assert runner.loaded_tools == []
