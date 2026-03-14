"""
StepUP AI - Lead Generation Tool
Streamlit Web Interface

Run with: streamlit run app.py
"""

import streamlit as st
import threading
import queue
import io
import os
import sys
import json
import time
import re
import math

import pandas as pd
from contextlib import redirect_stdout

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

from lead_generator import (
    load_profile, dry_run, generate_leads, generate_grid_points,
    get_output_paths, load_progress, stats as engine_stats,
)
from config import GOOGLE_API_KEY, PROFILES_DIR, OUTPUT_DIR


# =============================================================================
# Session State
# =============================================================================

def init_session_state():
    defaults = {
        "profile": None,
        "profile_name": None,
        "dry_run_output": None,
        "scan_running": False,
        "scan_logs": [],
        "scan_complete": False,
        "claude_messages": [],
        "anthropic_api_key": "",
        "generated_profile_code": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# =============================================================================
# Helper Functions
# =============================================================================

def compute_cost_estimate(profile):
    """Return cost estimate dict without printing."""
    grid_extent = profile.get("grid_extent", 1500)
    grid_step = profile.get("grid_step", 400)
    sample_area = profile["search_areas"][0]
    grid_points = generate_grid_points(sample_area[0], sample_area[1], grid_extent, grid_step)
    points_per_area = len(grid_points)

    num_areas = len(profile["search_areas"])
    num_primary = len(profile.get("primary_searches", []))
    num_secondary = len(profile.get("secondary_searches", []))
    total_searches = num_areas * points_per_area * (num_primary + num_secondary)

    search_cost = (total_searches / 1000) * 32
    detail_estimate = total_searches * 0.3
    detail_cost = (detail_estimate / 1000) * 17
    total_cost = search_cost + detail_cost

    return {
        "num_areas": num_areas,
        "points_per_area": points_per_area,
        "num_primary": num_primary,
        "num_secondary": num_secondary,
        "total_searches": total_searches,
        "search_cost": search_cost,
        "detail_cost": detail_cost,
        "total_cost": total_cost,
        "within_free_tier": total_cost <= 200,
    }


def capture_dry_run(profile):
    """Capture dry_run() printed output as a string."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        dry_run(profile)
    return buffer.getvalue()


def list_profiles():
    """Return list of available profile names."""
    profiles = []
    if os.path.exists(PROFILES_DIR):
        for f in sorted(os.listdir(PROFILES_DIR)):
            if f.endswith(".py") and not f.startswith("_") and f != "__init__.py":
                profiles.append(f[:-3])
    return profiles


def load_results_df(profile):
    """Load CSV output for a profile as a DataFrame."""
    paths = get_output_paths(profile)
    if os.path.exists(paths["csv"]):
        return pd.read_csv(paths["csv"])
    return None


class LogCapture:
    """Captures stdout to a queue while keeping original output."""
    def __init__(self, log_queue, original):
        self.queue = log_queue
        self.original = original

    def write(self, text):
        if text.strip():
            self.queue.put(text)
        self.original.write(text)

    def flush(self):
        self.original.flush()


def run_scan_in_thread(profile, log_queue, completion_flag):
    """Run generate_leads() in a background thread."""
    import lead_generator
    # Reset stats
    for k in lead_generator.stats:
        lead_generator.stats[k] = 0

    old_stdout = sys.stdout
    sys.stdout = LogCapture(log_queue, old_stdout)
    try:
        generate_leads(profile)
    except Exception as e:
        log_queue.put(f"ERROR: {e}")
    finally:
        sys.stdout = old_stdout
        completion_flag.append(True)


# =============================================================================
# Claude AI Functions
# =============================================================================

def get_anthropic_client():
    """Create Anthropic client from session state key."""
    key = st.session_state.get("anthropic_api_key", "")
    if not key:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=key)
    except Exception:
        return None


def build_claude_system_prompt(profile, cost_info):
    """Build system prompt with full profile context for cost optimization."""
    return f"""You are a cost optimization advisor for a Google Places API lead generation tool.

CURRENT PROFILE:
- Name: {profile['name']}
- Description: {profile['description']}
- Business type: {profile.get('included_type', 'None (text search only)')}
- Website filter: {profile['website_filter']}
- Location: {profile['location_name']}
- Search areas: {cost_info['num_areas']}
- Grid points per area: {cost_info['points_per_area']}
- Primary search terms ({cost_info['num_primary']}): {', '.join(profile.get('primary_searches', []))}
- Secondary search terms ({cost_info['num_secondary']}): {', '.join(profile.get('secondary_searches', []))}
- Grid step: {profile.get('grid_step', 400)}m
- Grid extent: {profile.get('grid_extent', 1500)}m
- Search radius: {profile.get('search_radius', 500)}m

COST BREAKDOWN:
- Total grid searches: {cost_info['total_searches']:,}
- Text Search API cost: ${cost_info['search_cost']:.2f}
- Place Details API cost: ${cost_info['detail_cost']:.2f}
- Total estimated cost: ${cost_info['total_cost']:.2f}
- Google free tier: $200/month
- Within free tier: {cost_info['within_free_tier']}

OPTIMIZATION LEVERS (explain these to the user):
1. Reduce search terms (each term multiplies total searches by num_areas x grid_points)
2. Increase grid_step (fewer grid points per area, risks minor coverage gaps)
3. Reduce grid_extent (smaller sub-grid per area center)
4. Fewer search areas (focus on high-value zones first)
5. Merge similar/overlapping search terms
6. Increase search_radius + grid_step together (cover same area with fewer calls)

Give specific, actionable suggestions with estimated cost impact. Be concise (3-5 bullet points).
Use simple language. Format numbers clearly."""


def ask_claude(profile, cost_info, user_message):
    """Send message to Claude and get optimization advice."""
    client = get_anthropic_client()
    if not client:
        return "Please enter your Anthropic API key in the sidebar."

    system = build_claude_system_prompt(profile, cost_info)

    messages = list(st.session_state.claude_messages)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        return f"Error: {e}"


def generate_profile_from_nl(description):
    """Use Claude to turn natural language into a PROFILE dict."""
    client = get_anthropic_client()
    if not client:
        return None, "Please enter your Anthropic API key first."

    template_path = os.path.join(PROFILES_DIR, "_template.py")
    with open(template_path, "r") as f:
        template_content = f.read()

    system = f"""You are a configuration generator for a Google Places API lead generation tool.
The user will describe what businesses they want to find and where.
You must output a valid Python PROFILE dict that matches this template:

{template_content}

Rules:
- Output ONLY valid Python code starting with PROFILE = {{
- search_areas must use real lat/lng coordinates for the described location
- For Paris, use arrondissement centers. For other cities, use neighborhood centers.
- Choose appropriate Google Places types (restaurant, hair_care, car_repair, dentist, gym, bakery, pharmacy, hotel, etc.)
- Generate search terms in the local language (French for France, etc.)
- Include a reasonable chain_blocklist for the industry
- Set website_filter based on what the user wants ("no_website" if they mention "without websites", "all" otherwise)
- name should be snake_case
- Keep grid_step and grid_extent conservative to manage costs
- DO NOT include any import statements or helper functions, just the PROFILE = {{ ... }} dict"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": description}],
        )
        return response.content[0].text, None
    except Exception as e:
        return None, str(e)


# =============================================================================
# UI: Sidebar - Claude AI Advisor
# =============================================================================

def render_sidebar():
    with st.sidebar:
        st.header("🤖 Claude AI Advisor")

        api_key = st.text_input(
            "Anthropic API Key",
            value=st.session_state.anthropic_api_key,
            type="password",
            help="Powers the AI search builder and cost optimizer",
        )
        st.session_state.anthropic_api_key = api_key

        st.divider()

        if st.session_state.profile is None:
            st.info("Load or create a profile to get optimization suggestions.")
            return

        profile = st.session_state.profile
        cost_info = compute_cost_estimate(profile)

        # Cost card
        st.metric("Estimated Cost", f"${cost_info['total_cost']:.0f}")
        if cost_info["within_free_tier"]:
            st.success(f"Within free tier ({cost_info['total_cost'] / 200 * 100:.0f}% of $200)")
        else:
            st.error(f"Exceeds free tier by \\${cost_info['total_cost'] - 200:.0f}")

        st.caption(f"{cost_info['total_searches']:,} total searches | "
                   f"{cost_info['num_areas']} areas | "
                   f"{cost_info['num_primary'] + cost_info['num_secondary']} terms")

        st.divider()

        # Analyze button
        if st.button("🔍 Analyze & Suggest Optimizations", use_container_width=True):
            with st.spinner("Claude is analyzing your config..."):
                reply = ask_claude(
                    profile, cost_info,
                    "Analyze this profile and suggest the top ways to reduce cost while keeping lead quality high. Be specific about numbers."
                )
                st.session_state.claude_messages.append(
                    {"role": "user", "content": "Analyze and suggest optimizations"}
                )
                st.session_state.claude_messages.append(
                    {"role": "assistant", "content": reply}
                )
                st.rerun()

        # Chat history
        for msg in st.session_state.claude_messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Chat input
        user_input = st.chat_input("Ask Claude about your config...")
        if user_input:
            st.session_state.claude_messages.append({"role": "user", "content": user_input})
            with st.spinner("Thinking..."):
                reply = ask_claude(profile, cost_info, user_input)
            st.session_state.claude_messages.append({"role": "assistant", "content": reply})
            st.rerun()


# =============================================================================
# UI: Search Builder Tab
# =============================================================================

def _parse_generated_profile(code):
    """Try to parse generated code into a PROFILE dict. Returns (profile, error)."""
    try:
        # Strip markdown code fences if Claude wrapped the output
        cleaned = code.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (e.g. ```python or ```)
            cleaned = re.sub(r"^```\w*\n?", "", cleaned, count=1)
            # Remove closing fence
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        local_ns = {}
        exec(cleaned, {"math": math}, local_ns)
        if "PROFILE" in local_ns:
            return local_ns["PROFILE"], None
        return None, "Generated code does not contain a PROFILE dict."
    except Exception as e:
        return None, str(e)


def _render_profile_preview(profile):
    """Render a nice visual summary of a parsed profile."""
    col_info, col_terms = st.columns(2)

    with col_info:
        st.markdown("**📌 Basic Info**")
        st.write(f"- **Name:** `{profile.get('name', 'N/A')}`")
        st.write(f"- **Description:** {profile.get('description', 'N/A')}")
        st.write(f"- **Location:** {profile.get('location_name', 'N/A')}")
        st.write(f"- **Business type:** {profile.get('included_type', 'Text search only')}")
        st.write(f"- **Website filter:** {profile.get('website_filter', 'all')}")
        st.write(f"- **Search areas:** {len(profile.get('search_areas', []))}")
        st.write(f"- **Grid:** radius {profile.get('search_radius', 500)}m, "
                 f"step {profile.get('grid_step', 400)}m, "
                 f"extent {profile.get('grid_extent', 1500)}m")

    with col_terms:
        st.markdown("**🔍 Search Terms**")
        primary = profile.get("primary_searches", [])
        secondary = profile.get("secondary_searches", [])
        if primary:
            st.write(f"**Primary** ({len(primary)}):")
            for t in primary:
                st.write(f"  - {t}")
        if secondary:
            st.write(f"**Secondary** ({len(secondary)}):")
            for t in secondary:
                st.write(f"  - {t}")

        blocklist = profile.get("chain_blocklist", [])
        if blocklist:
            st.write(f"**Chain blocklist:** {len(blocklist)} entries")


def _render_cost_breakdown(cost):
    """Render the cost breakdown with clear visual indicators."""
    st.markdown("---")
    st.subheader("💰 Cost Estimate (Dry Run)")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Search Areas", cost["num_areas"])
    col2.metric("Search Terms", cost["num_primary"] + cost["num_secondary"])
    col3.metric("Total API Calls", f"{cost['total_searches']:,}")
    col4.metric("Estimated Cost", f"${cost['total_cost']:.0f}")

    # Detailed cost table
    st.markdown(
        f"| Item | Detail |\n"
        f"|---|---|\n"
        f"| Grid points per area | {cost['points_per_area']} |\n"
        f"| Primary terms | {cost['num_primary']} |\n"
        f"| Secondary terms | {cost['num_secondary']} |\n"
        f"| Text Search cost | \\${cost['search_cost']:.2f} |\n"
        f"| Place Details cost | \\${cost['detail_cost']:.2f} |\n"
        f"| **Total** | **\\${cost['total_cost']:.2f}** |"
    )

    # Free tier status
    if cost["within_free_tier"]:
        pct = cost["total_cost"] / 200 * 100
        st.success(f"✅ Within free tier — using {pct:.0f}% of \\$200 monthly credit")
    else:
        overage = cost["total_cost"] - 200
        st.error(f"🚨 Exceeds \\$200 free tier by **\\${overage:.0f}**. "
                 "Use Claude AI Advisor in the sidebar to get cost reduction suggestions.")


def render_search_builder():
    st.header("🔎 Search Builder")

    # --- Input Section ---
    st.write("Describe what you want to search for in plain language:")

    nl_input = st.text_area(
        "search_description",
        placeholder="Example: Find Indian and Pakistani restaurants in Paris 18th arrondissement without websites",
        height=100,
        label_visibility="collapsed",
    )

    if st.button("✨ Generate Profile with AI", type="primary", disabled=not nl_input):
        if not st.session_state.anthropic_api_key:
            st.error("Please enter your Anthropic API key in the sidebar first.")
        else:
            with st.spinner("🤖 Claude is generating your search profile..."):
                result, error = generate_profile_from_nl(nl_input)
                if error:
                    st.error(error)
                else:
                    st.session_state.generated_profile_code = result
                    # Try to auto-parse so we can show preview + cost immediately
                    parsed, parse_err = _parse_generated_profile(result)
                    if parsed:
                        st.session_state._preview_profile = parsed
                        st.session_state._preview_error = None
                    else:
                        st.session_state._preview_profile = None
                        st.session_state._preview_error = parse_err
                    st.rerun()

    # --- Generated Profile: Live Preview + Cost ---
    if st.session_state.generated_profile_code:
        st.divider()

        # Visual preview of the profile
        preview_profile = st.session_state.get("_preview_profile")
        preview_error = st.session_state.get("_preview_error")

        if preview_profile:
            st.subheader("📋 Generated Profile Preview")
            _render_profile_preview(preview_profile)

            # Auto dry run / cost estimate
            cost = compute_cost_estimate(preview_profile)
            _render_cost_breakdown(cost)

        elif preview_error:
            st.error(f"Could not parse the generated profile: {preview_error}")

        # Raw code (collapsed by default)
        with st.expander("🔧 View / Edit Raw Profile Code", expanded=False):
            edited_code = st.text_area(
                "profile_code_editor",
                value=st.session_state.generated_profile_code,
                height=350,
                label_visibility="collapsed",
            )
            if edited_code != st.session_state.generated_profile_code:
                st.session_state.generated_profile_code = edited_code
                parsed, parse_err = _parse_generated_profile(edited_code)
                if parsed:
                    st.session_state._preview_profile = parsed
                    st.session_state._preview_error = None
                else:
                    st.session_state._preview_profile = None
                    st.session_state._preview_error = parse_err

        # Action buttons
        st.markdown("---")
        col_a, col_b, col_c = st.columns([2, 2, 1])
        with col_a:
            if st.button("✅ Accept & Load Profile", type="primary", use_container_width=True):
                if preview_profile:
                    st.session_state.profile = preview_profile
                    st.session_state.profile_name = preview_profile.get("name", "custom")
                    st.session_state.claude_messages = []
                    st.session_state.dry_run_output = None
                    st.session_state.generated_profile_code = None
                    st.session_state._preview_profile = None
                    st.success(f"Profile loaded: **{preview_profile.get('name')}**")
                    st.rerun()
                else:
                    st.error("Cannot load — profile has errors. Check the raw code.")
        with col_b:
            if st.button("📊 Full Dry Run Details", use_container_width=True):
                if preview_profile:
                    with st.spinner("Computing full dry run..."):
                        output = capture_dry_run(preview_profile)
                        st.session_state.dry_run_output = output
        with col_c:
            if st.button("🗑️ Discard", use_container_width=True):
                st.session_state.generated_profile_code = None
                st.session_state._preview_profile = None
                st.session_state._preview_error = None
                st.rerun()

        # Full dry run details (if requested)
        if st.session_state.dry_run_output:
            with st.expander("📊 Full Dry Run Output", expanded=True):
                st.code(st.session_state.dry_run_output)

    # --- Active Profile Section (if already loaded) ---
    elif st.session_state.profile:
        st.divider()
        st.subheader(f"Active Profile: {st.session_state.profile_name}")

        profile = st.session_state.profile
        _render_profile_preview(profile)

        cost = compute_cost_estimate(profile)
        _render_cost_breakdown(cost)

        if st.button("📊 Full Dry Run Details"):
            with st.spinner("Computing..."):
                output = capture_dry_run(profile)
                st.session_state.dry_run_output = output

        if st.session_state.dry_run_output:
            with st.expander("📊 Full Dry Run Output", expanded=True):
                st.code(st.session_state.dry_run_output)

    else:
        st.divider()
        st.info("Generate a profile above or load one from the Profiles tab.")


# =============================================================================
# UI: Run Scan Tab
# =============================================================================

def render_run_scan():
    st.header("🚀 Run Lead Generation Scan")

    if st.session_state.profile is None:
        st.warning("Load a profile first from Search Builder or Profiles tab.")
        return

    profile = st.session_state.profile
    cost = compute_cost_estimate(profile)

    # Pre-scan summary
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Searches", f"{cost['total_searches']:,}")
    col2.metric("Est. Cost", f"${cost['total_cost']:.0f}")
    col3.metric("Website Filter", profile["website_filter"])

    if not cost["within_free_tier"]:
        st.warning(f"⚠️ Estimated cost (\\${cost['total_cost']:.0f}) exceeds the \\$200 free tier. "
                   "Use Claude AI Advisor in the sidebar to get suggestions for reducing cost.")

    st.divider()

    # Start scan
    if not st.session_state.scan_running and not st.session_state.scan_complete:
        if GOOGLE_API_KEY == "YOUR_API_KEY_HERE" or not GOOGLE_API_KEY:
            st.error("Google API key not set in config.py")
            return

        if st.button("▶️ Start Scan", type="primary"):
            st.session_state.scan_running = True
            st.session_state.scan_logs = []
            st.session_state.scan_complete = False

            log_queue = queue.Queue()
            completion_flag = []

            # Store in session
            st.session_state._log_queue = log_queue
            st.session_state._completion_flag = completion_flag

            thread = threading.Thread(
                target=run_scan_in_thread,
                args=(profile, log_queue, completion_flag),
                daemon=True,
            )
            thread.start()
            st.rerun()

    # Running state
    if st.session_state.scan_running:
        log_queue = getattr(st.session_state, "_log_queue", None)
        completion_flag = getattr(st.session_state, "_completion_flag", [])

        # Drain queue
        if log_queue:
            while not log_queue.empty():
                try:
                    line = log_queue.get_nowait()
                    st.session_state.scan_logs.append(line)
                except queue.Empty:
                    break

        # Check completion
        if completion_flag:
            st.session_state.scan_running = False
            st.session_state.scan_complete = True
            st.rerun()

        # Progress
        current = 0
        total = cost["total_searches"]
        for line in reversed(st.session_state.scan_logs):
            m = re.search(r"\[(\d+)/", line)
            if m:
                current = int(m.group(1))
                break

        st.progress(min(current / max(total, 1), 1.0),
                    text=f"Scanning: {current:,} / {total:,} searches")

        # Live stats from engine
        import lead_generator
        scol1, scol2, scol3, scol4 = st.columns(4)
        scol1.metric("Leads Found", lead_generator.stats.get("leads_generated", 0))
        scol2.metric("Businesses Checked", lead_generator.stats.get("businesses_found", 0))
        scol3.metric("Chains Filtered", lead_generator.stats.get("chains_filtered", 0))
        scol4.metric("API Calls", lead_generator.stats.get("api_calls", 0))

        # Live log
        with st.container(height=400):
            st.code("\n".join(st.session_state.scan_logs[-80:]))

        st.button("⏹️ Stop Scan (press Ctrl+C in terminal to force stop)")

        # Auto-refresh
        time.sleep(2)
        st.rerun()

    # Completed state
    if st.session_state.scan_complete:
        st.success("✅ Scan complete!")
        st.balloons()

        with st.expander("Full scan log", expanded=False):
            st.code("\n".join(st.session_state.scan_logs))

        df = load_results_df(profile)
        if df is not None:
            st.metric("Total Leads Found", len(df))
            st.info("Go to the **Results** tab to view, filter, and download.")

        if st.button("🔄 Reset for New Scan"):
            st.session_state.scan_running = False
            st.session_state.scan_complete = False
            st.session_state.scan_logs = []
            st.rerun()


# =============================================================================
# UI: Results Tab
# =============================================================================

def render_results():
    st.header("📋 Results")

    if st.session_state.profile is None:
        st.warning("Load a profile first.")
        return

    profile = st.session_state.profile
    df = load_results_df(profile)

    if df is None or df.empty:
        st.info("No results yet. Run a scan first.")
        return

    # Find column names from profile
    cat_col = dist_col = rating_col = phone_col = name_col = None
    for header, key in profile["csv_columns"]:
        if key == "category":
            cat_col = header
        elif key == "district":
            dist_col = header
        elif key == "rating":
            rating_col = header
        elif key == "internationalPhoneNumber":
            phone_col = header
        elif key == "displayName":
            name_col = header

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Leads", len(df))

    if cat_col and cat_col in df.columns:
        col2.metric("Categories", df[cat_col].nunique())

    if dist_col and dist_col in df.columns:
        col3.metric("Districts", df[dist_col].nunique())

    if phone_col and phone_col in df.columns:
        with_phone = df[df[phone_col].notna() & (df[phone_col] != "")].shape[0]
        col4.metric("With Phone", with_phone)

    st.divider()

    # Filters
    filter_col1, filter_col2 = st.columns(2)

    selected_cat = "All"
    selected_dist = "All"

    with filter_col1:
        if cat_col and cat_col in df.columns:
            categories = ["All"] + sorted(df[cat_col].dropna().unique().tolist())
            selected_cat = st.selectbox("Filter by Category", categories)

    with filter_col2:
        if dist_col and dist_col in df.columns:
            districts = ["All"] + sorted(df[dist_col].dropna().unique().tolist())
            selected_dist = st.selectbox("Filter by District", districts)

    # Apply filters
    filtered = df.copy()
    if cat_col and selected_cat != "All":
        filtered = filtered[filtered[cat_col] == selected_cat]
    if dist_col and selected_dist != "All":
        filtered = filtered[filtered[dist_col] == selected_dist]

    # Data table
    st.dataframe(filtered, use_container_width=True, height=500)

    # Download
    csv_data = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"📥 Download CSV ({len(filtered)} leads)",
        data=csv_data,
        file_name=f"{profile['name']}_leads.csv",
        mime="text/csv",
    )

    # Charts
    if cat_col and cat_col in df.columns:
        st.subheader("Leads by Category")
        chart_data = df[cat_col].value_counts()
        st.bar_chart(chart_data)

    if dist_col and dist_col in df.columns:
        st.subheader("Leads by District")
        chart_data = df[dist_col].value_counts().head(20)
        st.bar_chart(chart_data)


# =============================================================================
# UI: Profiles Tab
# =============================================================================

def render_profiles():
    st.header("📁 Profiles")

    col_load, col_create = st.columns(2)

    with col_load:
        st.subheader("Load Existing Profile")
        profiles = list_profiles()

        if not profiles:
            st.info("No profiles found.")
        else:
            selected = st.selectbox("Select a profile", profiles)

            if st.button("📂 Load Profile", type="primary"):
                try:
                    profile = load_profile(selected)
                    st.session_state.profile = profile
                    st.session_state.profile_name = selected
                    st.session_state.dry_run_output = None
                    st.session_state.claude_messages = []
                    st.success(f"Loaded: {selected}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error loading profile: {e}")

    with col_create:
        st.subheader("Create New Profile")
        new_name = st.text_input("Profile name (snake_case)", placeholder="bakeries_lyon")

        if new_name:
            template_path = os.path.join(PROFILES_DIR, "_template.py")
            with open(template_path, "r") as f:
                template = f.read()

            edited = st.text_area("Edit profile code", value=template, height=400)

            if st.button("💾 Save Profile"):
                save_path = os.path.join(PROFILES_DIR, f"{new_name}.py")
                if os.path.exists(save_path):
                    st.error(f"Profile '{new_name}' already exists!")
                else:
                    with open(save_path, "w") as f:
                        f.write(edited)
                    st.success(f"Saved: {new_name}")
                    st.rerun()

    # Show active profile details
    if st.session_state.profile:
        st.divider()
        st.subheader(f"Active Profile: {st.session_state.profile_name}")

        profile = st.session_state.profile

        col_a, col_b = st.columns(2)

        with col_a:
            st.write("**Basic Info**")
            st.write(f"- **Description:** {profile['description']}")
            st.write(f"- **Business type:** {profile.get('included_type', 'Text search only')}")
            st.write(f"- **Website filter:** {profile['website_filter']}")
            st.write(f"- **Location:** {profile['location_name']}")
            st.write(f"- **Search areas:** {len(profile['search_areas'])}")

        with col_b:
            st.write("**Search Terms**")
            st.write("Primary:")
            for t in profile.get("primary_searches", []):
                st.write(f"- {t}")
            if profile.get("secondary_searches"):
                st.write("Secondary:")
                for t in profile["secondary_searches"]:
                    st.write(f"- {t}")

        st.write("**Grid Parameters**")
        st.write(f"Radius: {profile.get('search_radius', 500)}m | "
                 f"Step: {profile.get('grid_step', 400)}m | "
                 f"Extent: {profile.get('grid_extent', 1500)}m")

        # Show existing progress
        paths = get_output_paths(profile)
        if os.path.exists(paths["progress"]):
            progress = load_progress(paths)
            seen = len(progress.get("seen_place_ids", []))
            completed = len(progress.get("completed_scans", []))
            if seen > 0:
                st.info(f"📌 Resume data found: {seen} places checked, {completed} grid searches completed")


# =============================================================================
# Main App
# =============================================================================

def main():
    st.set_page_config(
        page_title="StepUP AI - Lead Generation",
        page_icon="🔍",
        layout="wide",
    )

    init_session_state()

    st.title("🔍 StepUP AI - Lead Generation Tool")

    # Sidebar
    render_sidebar()

    # Main tabs
    tab_search, tab_run, tab_results, tab_profiles = st.tabs([
        "🔎 Search Builder",
        "🚀 Run Scan",
        "📋 Results",
        "📁 Profiles",
    ])

    with tab_search:
        render_search_builder()

    with tab_run:
        render_run_scan()

    with tab_results:
        render_results()

    with tab_profiles:
        render_profiles()


if __name__ == "__main__":
    main()
