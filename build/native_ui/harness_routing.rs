//! Harness-only inference policy. Rendering, history and approvals stay native.
//!
//! Added to the pinned Apache-2.0 Codex source by the Harness distribution build.
use super::*;
use serde_json::Value;
use sha2::Digest as _;
use std::io::Read;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;
use std::sync::Mutex;

#[derive(Clone, Default)]
pub(super) struct Routing {
    pub(super) enabled: bool,
    pub(super) active: bool,
    pub(super) context: Option<Value>,
    selector: Option<Selector>,
    startup_error: Option<String>,
}

#[derive(Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Selector {
    schema: u32,
    python: PathBuf,
    script: PathBuf,
    script_sha256: String,
    mode: String,
    profiles: Option<PathBuf>,
}

impl Selector {
    pub(super) fn read(path: &Path) -> Result<Self, String> {
        let mut bytes = Vec::new();
        std::fs::File::open(path).map_err(|_| "Cannot read Harness integration settings")?
            .take(16385).read_to_end(&mut bytes).map_err(|_| "Cannot read Harness integration settings")?;
        if bytes.len() > 16384 {
            return Err("Oversized Harness integration settings".into());
        }
        let value: Self = serde_json::from_slice(&bytes).map_err(|_| "Invalid Harness integration settings")?;
        if value.schema != 1 || !value.python.is_absolute() || !value.script.is_absolute()
            || !matches!(value.mode.as_str(), "auto" | "manual")
            || value.profiles.as_ref().is_some_and(|path| !path.is_absolute()) {
            return Err("Unsupported Harness integration settings".into());
        }
        value.verify()?;
        Ok(value)
    }

    fn verify(&self) -> Result<(), String> {
        let file = std::fs::File::open(&self.script).map_err(|_| "Missing Harness selector")?;
        let mut bytes = Vec::new();
        file.take(262145).read_to_end(&mut bytes).map_err(|_| "Cannot read Harness selector")?;
        if bytes.len() > 262144 || format!("{:x}", sha2::Sha256::digest(&bytes)) != self.script_sha256 {
            return Err("Harness selector changed; run harness-codex doctor".into());
        }
        Ok(())
    }
}

impl Routing {
    pub(super) fn from_installation() -> Self {
        let path = std::env::current_exe().ok().and_then(|exe| {
            let package = exe.parent()?.parent()?;
            Some(package.with_extension("routing.json"))
        });
        let result = path.filter(|path| path.exists()).map(|path| Selector::read(&path));
        let (selector, startup_error) = match result {
            Some(Ok(value)) => (Some(value), None),
            Some(Err(error)) => (None, Some(error)),
            None => (None, None),
        };
        let enabled = selector.is_some();
        Self {
            enabled,
            active: selector.as_ref().is_some_and(|value| value.mode == "auto"),
            context: None,
            selector,
            startup_error,
        }
    }
}

#[cfg(test)]
pub(super) fn invoke_with_paths(
    payload: Value,
    python: std::ffi::OsString,
    script: std::ffi::OsString,
) -> Result<Value, String> {
    invoke_with_profiles(payload, python, script, None)
}

fn invoke_with_profiles(payload: Value, python: std::ffi::OsString, script: std::ffi::OsString,
                        profiles: Option<PathBuf>) -> Result<Value, String> {
    if !Path::new(&python).is_absolute() || !Path::new(&script).is_absolute() {
        return Err("Harness selector paths must be absolute".into());
    }
    let bytes = serde_json::to_vec(&payload).map_err(|_| "Invalid selector input")?;
    if bytes.len() > 256 * 1024 {
        return Err("Selector input exceeds its bounded size".into());
    }
    let mut command = Command::new(python);
    command.args(["-I", "-B"]).arg(script);
    command.env_remove("HARNESS_ROUTER_PROFILES");
    if let Some(profiles) = profiles {
        command.env("HARNESS_ROUTER_PROFILES", profiles);
    }
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .spawn()
        .map_err(|_| "Cannot start the Harness selector")?;
    let mut input = child.stdin.take().ok_or("Missing selector input pipe")?;
    let writer = std::thread::spawn(move || input.write_all(&bytes));
    let deadline = Instant::now() + Duration::from_secs(3);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = writer.join();
                return Err("Harness selector timed out; no task was retried".into());
            }
        }
    };
    let _ = writer.join();
    if !status.success() {
        return Err("Harness selector could not choose a supported model".into());
    }
    let mut result = Vec::new();
    child
        .stdout
        .take()
        .ok_or("Missing selector output pipe")?
        .take(8193)
        .read_to_end(&mut result)
        .map_err(|_| "Cannot read selector result")?;
    if result.len() > 8192 {
        return Err("Harness selector returned too much data".into());
    }
    serde_json::from_slice(&result).map_err(|_| "Invalid selector result".into())
}

impl ChatWidget {
    pub(super) fn report_harness_integration_problem(&mut self) {
        let error = self.harness_routing.lock().ok().and_then(|mut state| state.startup_error.take());
        if let Some(error) = error {
            self.add_error_message(format!("Harness Auto unavailable: {error}. Run harness-codex doctor. Native settings are retained."));
        }
    }

    pub(super) fn add_harness_auto_choice(&self, items: &mut Vec<SelectionItem>) {
        let Ok(state) = self.harness_routing.lock() else {
            return;
        };
        if !state.enabled || self.restrict_model_picker_to_luna_reserve() {
            return;
        }
        if state.active {
            for item in items.iter_mut() {
                item.is_current = false;
            }
        }
        let state_for_action = Arc::clone(&self.harness_routing);
        items.insert(0, SelectionItem {
            name: "Auto".into(),
            description: Some("Harness chooses model and reasoning for each new request. Reselect to start a new task.".into()),
            is_current: state.active,
            actions: vec![Box::new(move |tx| {
                if let Ok(mut state) = state_for_action.lock() {
                    state.active = true;
                    state.context = Some(serde_json::json!({
                        "tier": "balanced", "model": null, "effort": null,
                        "failures": 0, "active_task": false,
                    }));
                }
                tx.send(AppEvent::InsertHistoryCell(Box::new(history_cell::new_info_event(
                    "Harness Auto enabled for this conversation.".into(),
                    Some("Model and reasoning are selected before new turns; permissions remain unchanged.".into()),
                ))));
            })],
            dismiss_on_select: true,
            ..Default::default()
        });
    }

    pub(super) fn apply_harness_routing(&mut self, text: &str, has_images: bool) {
        let selector = self.harness_routing.lock().ok().and_then(|state| state.selector.clone());
        self.route_with_selector(text, has_images, move |payload| {
            let selector = selector.ok_or("Missing Harness integration settings")?;
            selector.verify()?;
            invoke_with_profiles(payload, selector.python.into_os_string(), selector.script.into_os_string(), selector.profiles)
        });
    }

    pub(super) fn inherit_harness_task_from_native_history(&mut self) {
        if let Ok(mut state) = self.harness_routing.lock() {
            if state.context.is_none() {
                let effort = self.effective_reasoning_effort();
                let encoded = serde_json::to_value(&effort).unwrap_or_default();
                let tier = if matches!(encoded.as_str(), Some("high" | "xhigh" | "max" | "ultra")) { "deep" } else { "balanced" };
                state.context = Some(serde_json::json!({"tier": tier, "model": self.current_model(),
                    "effort": effort, "failures": 0, "active_task": true}));
            }
        }
    }

    pub(super) fn route_with_selector(
        &mut self,
        text: &str,
        has_images: bool,
        selector: impl FnOnce(Value) -> Result<Value, String>,
    ) {
        let (active, context) = match self.harness_routing.lock() {
            Ok(state) => (state.enabled && state.active, state.context.clone()),
            Err(_) => return,
        };
        if !active || self.restrict_model_picker_to_luna_reserve() || text.trim().is_empty() {
            return;
        }
        // Steering an existing turn never changes its inference settings.
        if self.turn_lifecycle.agent_turn_running || text.len() > 32768 {
            return;
        }
        let models = self.model_catalog.try_list_models().unwrap_or_default();
        let payload = serde_json::json!({
            "prompt": text, "catalog": models, "context": context,
            "model": self.current_model(), "effort": self.effective_reasoning_effort(),
            "hasImages": has_images,
        });
        match selector(payload) {
            Ok(value) => {
                let Some(model) = value.get("model").and_then(Value::as_str) else {
                    return;
                };
                let effort = value
                    .get("effort")
                    .cloned()
                    .and_then(|value| serde_json::from_value::<ReasoningEffortConfig>(value).ok());
                let Some(effort) = effort else {
                    return;
                };
                // Validate the response against this native catalog independently.
                let valid = models.iter().any(|preset| {
                    preset.show_in_picker
                        && preset.model == model
                        && preset
                            .supported_reasoning_efforts
                            .iter()
                            .any(|option| option.effort == effort)
                        && (!has_images
                            || serde_json::to_value(&preset.input_modalities).is_ok_and(|values| {
                                values.as_array().is_some_and(|values| {
                                    values.contains(&Value::String("image".into()))
                                })
                            }))
                });
                if !valid {
                    self.add_error_message(
                        "Harness Auto returned an unsupported selection; keeping native settings."
                            .into(),
                    );
                    return;
                }
                let changed = self.current_model() != model
                    || self.effective_reasoning_effort() != Some(effort.clone());
                self.set_model(model);
                if self.active_mode_kind() == ModeKind::Plan {
                    self.set_plan_mode_reasoning_effort(Some(effort.clone()));
                } else {
                    self.set_reasoning_effort(Some(effort.clone()));
                }
                if let Ok(mut state) = self.harness_routing.lock() {
                    state.context = value.get("context").cloned();
                }
                if changed {
                    self.add_info_message(format!("Auto: {model} {effort}"), /*hint*/ None);
                }
            }
            Err(error) => {
                self.add_error_message(format!("Harness Auto: {error}. Keeping native settings."))
            }
        }
    }
}

pub(super) fn new_state() -> Arc<Mutex<Routing>> {
    Arc::new(Mutex::new(Routing::from_installation()))
}
