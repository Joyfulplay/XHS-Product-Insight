chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
  // Older Chromium builds may not support this setting.
});
