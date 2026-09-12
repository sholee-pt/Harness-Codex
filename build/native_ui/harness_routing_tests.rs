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
    let approval = chat.config.permissions.approval_policy.value();
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
