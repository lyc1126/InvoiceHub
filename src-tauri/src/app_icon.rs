//! Bundled App icons and the narrow runtime surface used by Host RPC.

use std::error::Error;
use std::fmt;
use std::fs;
use std::path::Path;

use serde_json::Value;
use tauri::{image::Image, tray::TrayIcon, AppHandle, Manager, Wry};

const MAIN_WINDOW_LABEL: &str = "main";
const STATE_FILE_NAME: &str = "app_icon_state.json";
const ORANGE_ICON: &[u8] = include_bytes!("../../web/static/app-icon/orange/icon_256.png");
const TEAL_ICON: &[u8] = include_bytes!("../../web/static/app-icon/teal/icon_256.png");
const VIOLET_ICON: &[u8] = include_bytes!("../../web/static/app-icon/violet/icon_256.png");

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AppIconId {
    Orange,
    Teal,
    Violet,
}

impl AppIconId {
    pub const DEFAULT: Self = Self::Orange;

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "orange" => Some(Self::Orange),
            "teal" => Some(Self::Teal),
            "violet" => Some(Self::Violet),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Orange => "orange",
            Self::Teal => "teal",
            Self::Violet => "violet",
        }
    }

    fn bytes(self) -> &'static [u8] {
        match self {
            Self::Orange => ORANGE_ICON,
            Self::Teal => TEAL_ICON,
            Self::Violet => VIOLET_ICON,
        }
    }
}

#[derive(Debug)]
pub enum AppIconError {
    ImageUnavailable,
    TrayUnavailable,
    ApplyFailed,
}

impl fmt::Display for AppIconError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::ImageUnavailable => "bundled App icon is unavailable",
            Self::TrayUnavailable => "desktop tray icon is unavailable",
            Self::ApplyFailed => "desktop App icon update failed",
        })
    }
}

impl Error for AppIconError {}

pub fn load_selected(runtime_dir: &Path) -> AppIconId {
    let state_path = runtime_dir.join("local_state").join(STATE_FILE_NAME);
    let Ok(bytes) = fs::read(state_path) else {
        return AppIconId::DEFAULT;
    };
    let Ok(value) = serde_json::from_slice::<Value>(&bytes) else {
        return AppIconId::DEFAULT;
    };
    value
        .as_object()
        .and_then(|object| object.get("icon"))
        .and_then(Value::as_str)
        .and_then(AppIconId::parse)
        .unwrap_or(AppIconId::DEFAULT)
}

pub fn image_for(icon_id: AppIconId) -> Result<Image<'static>, AppIconError> {
    Image::from_bytes(icon_id.bytes()).map_err(|_| AppIconError::ImageUnavailable)
}

pub fn apply(
    app: &AppHandle<Wry>,
    next_icon: AppIconId,
    previous_icon: AppIconId,
) -> Result<(), AppIconError> {
    let next_image = image_for(next_icon)?;
    let previous_image = image_for(previous_icon)?;
    let tray = app
        .try_state::<TrayIcon>()
        .ok_or(AppIconError::TrayUnavailable)?;
    tray.set_icon(Some(next_image.clone()))
        .map_err(|_| AppIconError::ApplyFailed)?;

    if let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        if window.set_icon(next_image).is_err() {
            // The runtime file still names the previous icon until Python receives success.
            // Restore the tray before rejecting so the two visible native surfaces stay aligned.
            let _ = tray.set_icon(Some(previous_image));
            return Err(AppIconError::ApplyFailed);
        }
    }
    Ok(())
}
