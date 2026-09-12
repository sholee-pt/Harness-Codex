use super::*;

#[tokio::test]
async fn harness_auto_model_picker_uses_original_view() {
    let (mut chat, _rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    {
        let mut state = chat.harness_routing.lock().expect("routing state");
        state.enabled = true;
        state.active = true;
    }
    let presets = chat.model_catalog.try_list_models().expect("native catalog");
    chat.open_model_popup_with_presets(presets);
    let popup = render_bottom_popup(&chat, /*width*/ 100);
    assert!(popup.contains("Auto"));
    insta::assert_snapshot!("harness_auto_native_model_picker", popup);
}

#[tokio::test]
async fn harness_auto_selection_keeps_model_and_permissions_until_request() {
    let (chat, mut rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    let model = chat.current_model().to_string();
    let effort = chat.effective_reasoning_effort();
    let approval = chat.config.permissions.approval_policy.value().clone();
    while rx.try_recv().is_ok() {}
    chat.harness_routing.lock().expect("routing state").enabled = true;
    let mut items = Vec::new();
    chat.add_harness_auto_choice(&mut items);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0].name, "Auto");
    (items[0].actions[0])(&chat.app_event_tx);
    assert!(chat.harness_routing.lock().expect("routing state").active);
    assert_eq!(chat.current_model(), model);
    assert_eq!(chat.effective_reasoning_effort(), effort);
    assert_eq!(chat.config.permissions.approval_policy.value(), approval);
    while let Ok(event) = rx.try_recv() {
        assert_matches!(event, AppEvent::InsertHistoryCell(_));
    }
}

#[tokio::test]
async fn disabled_harness_keeps_original_model_choices() {
    let (mut chat, _rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    chat.harness_routing.lock().expect("routing state").enabled = false;
    let presets = chat.model_catalog.try_list_models().expect("native catalog");
    chat.open_model_popup_with_presets(presets.clone());
    let before = render_bottom_popup(&chat, /*width*/ 100);
    chat.open_model_popup_with_presets(presets);
    assert_eq!(render_bottom_popup(&chat, /*width*/ 100), before);
    let mut items = Vec::new();
    chat.add_harness_auto_choice(&mut items);
    assert!(items.is_empty());
}

#[tokio::test]
async fn native_routing_hook_changes_only_supported_inference_settings() {
    let (mut chat, _rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    let approval = chat.config.permissions.approval_policy.value().clone();
    {
        let mut state = chat.harness_routing.lock().expect("routing state");
        state.enabled = true;
        state.active = true;
    }
    let preset = chat.model_catalog.try_list_models().expect("models")
        .into_iter().find(|preset| preset.show_in_picker && !preset.supported_reasoning_efforts.is_empty())
        .expect("selectable model");
    let effort = preset.supported_reasoning_efforts[0].effort.clone();
    chat.route_with_selector("Review this request", /*has_images*/ false, |payload| {
        assert_eq!(payload["prompt"], "Review this request");
        serde_json::from_value::<Vec<ModelPreset>>(payload["catalog"].clone()).expect("native catalog shape");
        Ok(serde_json::json!({"model": preset.model, "effort": effort, "context": null}))
    });
    assert_eq!(chat.current_model(), preset.model);
    assert_eq!(chat.effective_reasoning_effort(), Some(effort.clone()));
    assert_eq!(chat.config.permissions.approval_policy.value(), approval);
    chat.route_with_selector("Unsupported model", /*has_images*/ false, |_| {
        Ok(serde_json::json!({"model": "not-in-the-native-catalog", "effort": "high", "context": null}))
    });
    assert_eq!(chat.current_model(), preset.model);
    assert_eq!(chat.effective_reasoning_effort(), Some(effort));
    chat.turn_lifecycle.agent_turn_running = true;
    chat.route_with_selector("Steer this turn", /*has_images*/ false, |_| panic!("Steering must not select again"));
}

#[test]
fn native_rust_bridge_executes_the_isolated_conda_selector() {
    let prefix = PathBuf::from(std::env::var_os("CONDA_PREFIX").expect("Run tests in the harness environment"));
    let python = prefix.join(if cfg!(windows) { "python.exe" } else { "bin/python" });
    let script = std::env::var_os("HARNESS_SELECTOR_TEST_SCRIPT").expect("Selector integration fixture path");
    let payload = serde_json::json!({
        "prompt": "Fix README wording.", "context": null, "model": "gpt-6-astra", "effort": "high", "hasImages": false,
        "catalog": [
            {"model": "gpt-5.6-luna", "show_in_picker": true, "is_default": false, "default_reasoning_effort": "low",
             "input_modalities": ["text"], "supported_reasoning_efforts": [{"effort": "low"}]},
            {"model": "gpt-6-astra", "show_in_picker": true, "is_default": true, "default_reasoning_effort": "high",
             "input_modalities": ["text", "image"], "supported_reasoning_efforts": [{"effort": "high"}]}
        ],
    });
    let value = super::super::harness_routing::invoke_with_paths(payload, python.into_os_string(), script).expect("native selector");
    assert_eq!(value["model"], "gpt-5.6-luna");
    assert_eq!(value["effort"], "low");
}
