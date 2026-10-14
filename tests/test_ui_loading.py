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
        callback = app.demo.fns[dependency["id"]].fn
        if callback in work or callback.__name__ == "export_callback":
            assert dependency["queue"] is True
            assert dependency["show_progress"] == "minimal"
            assert len(dependency["show_progress_on"]) == 1
            assert dependency["trigger_mode"] in {"once", "always_last"}
        else:
            assert dependency["queue"] is False
            assert dependency["show_progress"] == "hidden"


def test_failed_workflows_do_not_run_render_reset_or_save_followups():
    import app

    for dependency in app.demo.config["dependencies"]:
        if dependency["trigger_after"] is not None:
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
