# =============================================================================
# StepUP AI - Lead Generation Tool
# Global Configuration (shared across all profiles)
# =============================================================================

# Your Google Maps API key (Places API must be enabled)
# Set via .streamlit/secrets.toml (local) or Streamlit Cloud Secrets (deployed)
import os
try:
    import streamlit as st
    GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
except Exception:
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# =============================================================================
# Rate Limiting
# =============================================================================

# Delay between API calls in seconds
API_DELAY = 0.3

# Save progress every N leads
SAVE_INTERVAL = 50

# =============================================================================
# Directories
# =============================================================================

# Where search profiles are stored
PROFILES_DIR = "profiles"

# Where output (CSV, progress) is stored per profile
# Use temp dir on Streamlit Cloud (container filesystem may not be writable)
import tempfile
_default_output = os.path.join(tempfile.gettempdir(), "stepup_output")
OUTPUT_DIR = os.environ.get("STEPUP_OUTPUT_DIR", _default_output)
