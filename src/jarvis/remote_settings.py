"""Preferences that an administrator companion may configure on the core.

Host paths, command grants and local inference remain host/executor settings.
Device microphone selection is stored by the companion, never on the core.
"""

COMPANION_SETTINGS = frozenset({
    "python_sandbox_enabled", "browser_enabled",
    "cloud_provider", "cloud_model", "cloud_base_url", "cloud_api_key",
    "cloud_reasoning_effort", "model_input_usd_per_million", "model_output_usd_per_million",
    "monthly_budget_usd", "max_parallel_tasks", "max_output_tokens", "max_agent_steps",
    "task_timeout_seconds", "model_request_timeout_seconds", "tool_timeout_seconds",
    "timezone", "ui_language", "language", "response_language", "response_personality", "weather_location",
    "weather_latitude", "weather_longitude", "weather_refresh_minutes", "quiet_hours",
    "transcript_retention_days", "operation_log_retention_days", "search_provider",
    "search_api_key", "calendar_provider", "calendar_ics_url", "calendar_access_token",
    "calendar_refresh_token", "calendar_client_id", "calendar_client_secret", "calendar_tenant_id",
    "second_brain_url", "second_brain_token", "second_brain_auth",
    "second_brain_allow_corrections", "memory_capture", "memory_recall_token_budget",
    "voice_enabled", "wake_enabled", "wake_phrase", "followup_seconds", "end_of_turn_ms",
    "listen_timeout_seconds", "tts_voice", "voice_on_lock_screen", "desktop_voice_provider",
    "desktop_voice_api_key", "desktop_voice_model", "desktop_voice_name", "desktop_voice_style",
    "desktop_voice_duplex", "desktop_voice_max_session_seconds", "desktop_voice_idle_seconds",
    "desktop_voice_rate_usd_per_minute", "lighting_enabled", "telephony_enabled",
    "telephony_tunnel_mode", "telephony_public_base_url", "telephony_account_id",
    "telephony_auth_token", "telephony_from_number", "owner_phone_number", "phone_inbound_enabled",
    "phone_pin_enabled", "phone_pin", "phone_api_key", "phone_max_call_seconds",
    "phone_daily_budget_usd", "phone_minute_rate_usd", "phone_stt_provider", "phone_stt_model",
    "phone_tts_model", "phone_tts_voice", "phone_local_tts_voice", "phone_local_stt_model",
})
