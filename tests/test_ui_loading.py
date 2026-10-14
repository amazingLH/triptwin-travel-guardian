"""Loading scope and explicit completion of local UI operations."""

from triptwin.functional_examples import example_trip


def test_render_and_save_callbacks_never_queue_or_cover_existing_results():
    import app

    work = {
        app.parse_current_import, app.generate_plan_b_guarded, app.confirm_import,
        app.run_live_inspection_guarded, app.answer_question_guarded, app.check_risks,
        app.apply_local_option, app.apply_tripgraph_edits, app.create_new_history_session,
        app.open_history_session, app.delete_current_history_session, app.clear_all_history_sessions,
    }
    for dependency in app.demo.config["dependencies"]:
        bound_callback = app.demo.fns[dependency["id"]].fn
        callback = getattr(bound_callback, "__wrapped__", bound_callback)
        if callback in work or callback.__name__ == "export_callback":
            assert dependency["queue"] is True
            assert len(dependency["show_progress_on"]) == 1
            assert dependency["trigger_mode"] in {"once", "always_last"}
            if hasattr(bound_callback, "__wrapped__"):
                assert dependency["show_progress"] == "full"
                target = next(c for c in app.demo.config["components"] if c["id"] == dependency["show_progress_on"][0])
                assert "operation-progress" in target["props"]["elem_classes"]
                assert target["id"] in dependency["outputs"]
            else:
                assert dependency["show_progress"] == "minimal"
        else:
            assert dependency["queue"] is False
            assert dependency["show_progress"] == "hidden"


def test_failed_workflows_do_not_run_render_reset_or_save_followups():
    import app

    for dependency in app.demo.config["dependencies"]:
        if dependency["trigger_after"] is not None:
            if dependency["trigger_only_on_failure"]:
                assert dependency["queue"] is False
                assert dependency["show_progress"] == "hidden"
                for identifier in dependency["outputs"]:
                    component = next(c for c in app.demo.config["components"] if c["id"] == identifier)
                    assert "operation-progress" in component["props"]["elem_classes"]
            else:
                assert dependency["trigger_only_on_success"] is True


def test_background_state_events_are_replaced_by_explicit_snapshot_outputs():
    import app

    state_ids = {
        component["id"] for component in app.demo.config["components"]
        if component["type"] == "state"
    }
    for dependency in app.demo.config["dependencies"]:
        assert not any(target in state_ids and event == "change" for target, event in dependency["targets"])

    result = app.persist_current_session(
        None, {"trip": example_trip("multi")}, "built", True,
        "risk", "plan", "trace", [], "amap", "inspection",
    )
    assert len(result) == 10
    assert result[0] == result[3]  # server snapshot and browser mirror together
    assert result[-1]["visible"] is True
    assert result[0]["sessions"][0]["snapshot"]["risks"] == "risk"


def test_autosave_keeps_user_completion_values_instead_of_resetting_inputs():
    import app

    draft = example_trip("multi")
    draft["constraints"].pop("budget_cny")
    rows = [["constraints.budget_cny", "总预算", "3200"]]
    result = app.persist_current_session(
        None, {"draft_trip": draft}, "pending", False,
        "", "", "", [], "", "", [], "", rows,
    )
    assert result[5] == rows
    assert result[3]["sessions"][0]["snapshot"]["trip_state"]["completion_rows"] == rows


def test_timed_operation_reports_real_execution_duration_and_propagates_error(monkeypatch):
    import app
    import pytest

    moments = iter([10, 12.125])
    monkeypatch.setattr(app.time, "perf_counter", lambda: next(moments))
    callback = app.timed_operation(lambda: ("result", {"state": "kept"}), "检查")
    result = callback()
    assert result[:2] == ("result", {"state": "kept"})
    assert "2.12 秒" in result[-1]
    monkeypatch.setattr(app.time, "perf_counter", lambda: 10)
    def failed():
        raise app.gr.Error("请先输入预算")
    with pytest.raises(app.gr.Error, match="请先输入预算"):
        app.timed_operation(failed, "构建")()


def test_timing_wrapper_keeps_request_injection_for_usage_guards():
    import app
    from gradio.helpers import special_args

    request = app.gr.Request()
    wrapped = app.timed_operation(app.run_live_inspection_guarded, "巡检")
    arguments, _, _, _ = special_args(wrapped, [{}, True, {}], request=request)
    assert arguments[-1] is request
