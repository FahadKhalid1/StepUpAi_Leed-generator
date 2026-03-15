#!/usr/bin/env python3
"""
StepUP AI - Lead Generation Tool

Finds businesses without websites (or with websites) using Google Places API.
Supports any business type, any location, via configurable search profiles.

Usage:
    python lead_generator.py --profile restaurants_paris
    python lead_generator.py --profile vtc_idf
    python lead_generator.py --profile vtc_idf --dry-run

Create new profiles by copying profiles/_template.py
"""

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import sys
import time

from config import GOOGLE_API_KEY, API_DELAY, SAVE_INTERVAL, PROFILES_DIR, OUTPUT_DIR

# Google Places API (New) endpoints
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Fields to request (controls billing - only request what we need)
SEARCH_FIELDS = "places.id,places.displayName,places.formattedAddress,places.types,places.location"
DETAIL_FIELDS = "id,displayName,formattedAddress,internationalPhoneNumber,rating,userRatingCount,websiteUri,googleMapsUri,types,primaryType"

# Stats
stats = {
    "api_calls": 0,
    "businesses_found": 0,
    "leads_generated": 0,
    "chains_filtered": 0,
    "duplicates_skipped": 0,
}


# =============================================================================
# Profile & Path Management
# =============================================================================

def load_profile(profile_name):
    """Load a search profile by name from profiles/ directory."""
    profile_path = os.path.join(PROFILES_DIR, f"{profile_name}.py")
    if not os.path.exists(profile_path):
        print(f"ERROR: Profile '{profile_name}' not found at {profile_path}")
        print(f"\nAvailable profiles:")
        for f in sorted(os.listdir(PROFILES_DIR)):
            if f.endswith(".py") and not f.startswith("_"):
                print(f"  - {f[:-3]}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location(profile_name, profile_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PROFILE


def get_output_paths(profile):
    """Return output paths for a profile."""
    import tempfile

    out_dir = os.path.join(OUTPUT_DIR, profile["name"])
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        # Fallback to system temp dir if primary path fails (e.g. Streamlit Cloud)
        out_dir = os.path.join(tempfile.gettempdir(), "stepup_output", profile["name"])
        os.makedirs(out_dir, exist_ok=True)
    return {
        "dir": out_dir,
        "csv": os.path.join(out_dir, "leads.csv"),
        "progress": os.path.join(out_dir, "progress.json"),
    }


# =============================================================================
# API Key Check
# =============================================================================

def check_api_key():
    """Verify the API key is set."""
    if GOOGLE_API_KEY == "YOUR_API_KEY_HERE" or not GOOGLE_API_KEY:
        print("ERROR: Please set your Google API key in config.py")
        print()
        print("Steps to get an API key:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project (or select existing)")
        print("3. Enable 'Places API (New)' in APIs & Services > Library")
        print("4. Create an API key in APIs & Services > Credentials")
        print("5. Paste the key in config.py as GOOGLE_API_KEY")
        sys.exit(1)


# =============================================================================
# Progress Management
# =============================================================================

def load_progress(paths):
    """Load scan progress from file for resume capability."""
    if os.path.exists(paths["progress"]):
        with open(paths["progress"], "r") as f:
            progress = json.load(f)
    else:
        progress = {"completed_scans": [], "seen_place_ids": []}

    # Extra safety: also load place IDs from the existing CSV output
    if os.path.exists(paths["csv"]):
        existing_ids = set(progress.get("seen_place_ids", []))
        with open(paths["csv"], "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = row.get("Place ID", "")
                if pid:
                    existing_ids.add(pid)
        progress["seen_place_ids"] = list(existing_ids)

    return progress


def save_progress(progress, paths):
    """Save scan progress to file."""
    with open(paths["progress"], "w") as f:
        json.dump(progress, f, indent=2)


# =============================================================================
# Grid Generation
# =============================================================================

def generate_grid_points(center_lat, center_lng, extent_m, step_m):
    """Generate a grid of (lat, lng) points around a center coordinate."""
    points = []
    lat_step = step_m / 111320
    lng_step = step_m / (111320 * math.cos(math.radians(center_lat)))

    steps = int(extent_m / step_m)

    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            lat = center_lat + (i * lat_step)
            lng = center_lng + (j * lng_step)
            points.append((lat, lng))

    return points


# =============================================================================
# Filtering & Classification
# =============================================================================

def is_chain(name, blocklist):
    """Check if a business name matches a known chain/blocklist."""
    name_lower = name.lower().strip()
    for chain in blocklist:
        if chain.lower() in name_lower:
            return True
    return False


def classify_category(name, types, category_keywords):
    """Classify business category based on name and Google place types."""
    if not category_keywords:
        return "Uncategorized"
    combined = (name + " " + " ".join(types)).lower()

    for category, keywords in category_keywords.items():
        for kw in keywords:
            if kw in combined:
                return category

    return "Other"


def extract_district(address, profile):
    """Extract district/postal code from address using profile's pattern."""
    if not address:
        return "Unknown"

    pattern = profile.get("district_pattern")
    if not pattern:
        return "N/A"

    match = re.search(pattern, address)
    if match:
        # Use capture group 1 if available, otherwise use the full match
        try:
            raw = match.group(1)
        except IndexError:
            raw = match.group(0)
        fmt = profile.get("district_format", "{num}")
        try:
            num = int(raw)
            # Special handling for Paris arrondissements (1er vs 2e)
            if "Paris" in fmt and num == 1:
                return fmt.replace("{num}", str(num)).replace("1e", "1er")
            return fmt.replace("{num}", str(num)).replace("{num:05d}", f"{num:05d}")
        except (ValueError, TypeError):
            return raw

    fallback_check = profile.get("district_fallback_check", "")
    if fallback_check and fallback_check.lower() in address.lower():
        return profile.get("district_fallback_label", "Unknown area")

    return profile.get("district_outside_label", "Unknown")


# =============================================================================
# Google Places API
# =============================================================================

def search_nearby(lat, lng, keyword, profile):
    """Search for businesses near a point using Text Search API."""
    import requests

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": SEARCH_FIELDS,
    }

    body = {
        "textQuery": f"{keyword} {profile['location_name']}",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": profile["search_radius"],
            }
        },
        "maxResultCount": 20,
        "languageCode": profile.get("language_code", "fr"),
    }

    # Only add includedType if the profile specifies one
    if profile.get("included_type"):
        body["includedType"] = profile["included_type"]

    try:
        stats["api_calls"] += 1
        response = requests.post(TEXT_SEARCH_URL, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("places", [])
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            print("  Rate limited. Waiting 60 seconds...")
            time.sleep(60)
            return search_nearby(lat, lng, keyword, profile)
        elif response.status_code == 403:
            print("  ERROR 403: API key issue. Check that Places API (New) is enabled.")
            print(f"  Response: {response.text}")
            return []
        else:
            print(f"  Search error ({response.status_code}): {e}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"  Network error: {e}")
        return []
    except Exception as e:
        print(f"  Unexpected error in search: {e}")
        return []


def get_place_details(place_id):
    """Get detailed info for a place."""
    import requests

    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": DETAIL_FIELDS,
    }

    try:
        stats["api_calls"] += 1
        url = PLACE_DETAILS_URL.format(place_id=place_id)
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            print("  Rate limited. Waiting 60 seconds...")
            time.sleep(60)
            return get_place_details(place_id)
        else:
            print(f"  Details error ({response.status_code}): {e}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"  Network error: {e}")
        return None
    except Exception as e:
        print(f"  Unexpected error in details: {e}")
        return None


# =============================================================================
# Output
# =============================================================================

def save_results(leads, profile, paths):
    """Save lead list to CSV using profile's column definitions."""
    if not leads:
        return

    fieldnames = [col[0] for col in profile["csv_columns"]]

    with open(paths["csv"], "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        # Sort: priority first, then by category, then by name
        sorted_leads = sorted(
            leads,
            key=lambda r: (
                0 if r.get("Priority", r.get("priority", "")) == "Primary" else 1,
                r.get("Category", r.get("category", "")),
                r.get("Business Name", r.get("displayName", "")),
            ),
        )

        for lead in sorted_leads:
            writer.writerow(lead)

    print(f"  Saved {len(leads)} leads to {paths['csv']}")


# =============================================================================
# Main Lead Generation Engine
# =============================================================================

def generate_leads(profile):
    """Main lead generation function - works with any profile."""
    import requests as _req

    check_api_key()

    # --- Pre-flight connectivity check ---
    print("Running pre-flight checks...")
    print(f"  API key: {GOOGLE_API_KEY[:8]}...{GOOGLE_API_KEY[-4:]}" if len(GOOGLE_API_KEY) > 12 else "  API key: (short key)")
    print(f"  Python: {sys.version}")
    print(f"  OS user: {os.environ.get('USER', 'unknown')}")
    print(f"  HOME: {os.environ.get('HOME', 'unknown')}")

    # Test basic HTTPS connectivity
    try:
        test_resp = _req.get("https://maps.googleapis.com", timeout=10)
        print(f"  Network: OK (status {test_resp.status_code})")
    except Exception as e:
        print(f"  Network: FAILED - {type(e).__name__}: {e}")

    # Test a minimal Places API call
    try:
        test_headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_API_KEY,
            "X-Goog-FieldMask": "places.id",
        }
        test_body = {
            "textQuery": "restaurant Paris",
            "maxResultCount": 1,
        }
        test_resp = _req.post(TEXT_SEARCH_URL, headers=test_headers, json=test_body, timeout=15)
        if test_resp.status_code == 200:
            places_count = len(test_resp.json().get("places", []))
            print(f"  API test: OK ({places_count} place(s) returned)")
        else:
            print(f"  API test: HTTP {test_resp.status_code} - {test_resp.text[:200]}")
    except Exception as e:
        print(f"  API test: FAILED - {type(e).__name__}: {e}")
    print()

    paths = get_output_paths(profile)

    print("=" * 60)
    print("STEPUP AI - LEAD GENERATION TOOL")
    print(f"Profile: {profile['description']}")
    print(f"Filter: {profile['website_filter']}")
    print(f"Output dir: {paths['dir']}")
    print("=" * 60)
    print()

    # Load previous progress
    progress = load_progress(paths)
    seen_place_ids = set(progress.get("seen_place_ids", []))
    completed_scans = set(tuple(s) for s in progress.get("completed_scans", []))
    leads = []

    # Load existing results if resuming
    if os.path.exists(paths["csv"]) and seen_place_ids:
        with open(paths["csv"], "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            leads = list(reader)
        print(f"Resuming: {len(leads)} leads already found")
        print(f"  {len(seen_place_ids)} places already checked")
        print(f"  {len(completed_scans)} grid searches completed")
        print()

    # Build search queue
    all_searches = []
    grid_extent = profile.get("grid_extent", 1500)
    grid_step = profile.get("grid_step", 400)

    for area_lat, area_lng, area_name in profile["search_areas"]:
        grid_points = generate_grid_points(area_lat, area_lng, grid_extent, grid_step)

        # Priority searches
        for search_term in profile.get("primary_searches", []):
            for lat, lng in grid_points:
                scan_key = (round(lat, 5), round(lng, 5), search_term)
                if scan_key not in completed_scans:
                    all_searches.append((lat, lng, search_term, area_name, "Primary"))

        # Secondary searches
        for search_term in profile.get("secondary_searches", []):
            for lat, lng in grid_points:
                scan_key = (round(lat, 5), round(lng, 5), search_term)
                if scan_key not in completed_scans:
                    all_searches.append((lat, lng, search_term, area_name, "Secondary"))

    total_searches = len(all_searches)
    print(f"Total grid searches to perform: {total_searches}")
    print(f"Estimated API calls: {total_searches} (search) + details calls")
    print(f"Output: {paths['csv']}")
    print()

    if total_searches == 0:
        print("Nothing new to scan. All grid searches already completed.")
        return

    start_time = time.time()
    current_area = ""
    current_search = ""

    blocklist = profile.get("chain_blocklist", [])
    category_keywords = profile.get("category_keywords", {})
    website_filter = profile.get("website_filter", "no_website")

    # Check for external stop flag (set by Streamlit UI)
    stop_flag = profile.get("_stop_flag")

    try:
        for idx, (lat, lng, search_term, area_name, priority) in enumerate(all_searches):
            # Check if stop was requested
            if stop_flag and stop_flag.is_set():
                print("\n⏹️ Scan stopped by user.")
                break

            # Progress header
            if area_name != current_area or search_term != current_search:
                current_area = area_name
                current_search = search_term
                elapsed = time.time() - start_time
                print(f"\n[{idx + 1}/{total_searches}] {area_name} - Searching: {search_term}")
                print(f"  Stats: {stats['leads_generated']} leads | "
                      f"{stats['businesses_found']} checked | "
                      f"{stats['chains_filtered']} chains filtered | "
                      f"{stats['api_calls']} API calls | "
                      f"{elapsed:.0f}s elapsed")

            # Search
            try:
                places = search_nearby(lat, lng, search_term, profile)
            except Exception as e:
                print(f"  ERROR in search call: {e}")
                places = []
            time.sleep(API_DELAY)

            for place in places:
              try:
                place_id = place.get("id", "")

                # Skip duplicates
                if place_id in seen_place_ids:
                    stats["duplicates_skipped"] += 1
                    continue

                seen_place_ids.add(place_id)

                name = place.get("displayName", {}).get("text", "Unknown")
                types = place.get("types", [])

                # Skip chains
                if is_chain(name, blocklist):
                    stats["chains_filtered"] += 1
                    continue

                stats["businesses_found"] += 1

                # Get details
                try:
                    details = get_place_details(place_id)
                except Exception as e:
                    print(f"  ERROR in details call: {e}")
                    details = None
                time.sleep(API_DELAY)

                if details is None:
                    continue

                website = details.get("websiteUri", "")

                # Apply website filter
                if website_filter == "no_website" and website:
                    continue  # Skip businesses WITH websites
                elif website_filter == "has_website" and not website:
                    continue  # Skip businesses WITHOUT websites
                # "all" keeps everything

                stats["leads_generated"] += 1

                address = details.get("formattedAddress", "")
                category = classify_category(name, types, category_keywords)
                detected_priority = priority
                if priority == "Secondary" and category != "Other" and category != "Uncategorized":
                    detected_priority = "Primary"

                # Build lead data
                detail_data = {
                    "displayName": details.get("displayName", {}).get("text", name),
                    "category": category,
                    "priority": detected_priority,
                    "formattedAddress": address,
                    "district": extract_district(address, profile),
                    "internationalPhoneNumber": details.get("internationalPhoneNumber", ""),
                    "websiteUri": website,
                    "rating": details.get("rating", ""),
                    "userRatingCount": details.get("userRatingCount", ""),
                    "googleMapsUri": details.get("googleMapsUri", ""),
                    "place_id": place_id,
                }

                # Map to CSV columns
                lead = {}
                for col_header, data_key in profile["csv_columns"]:
                    lead[col_header] = detail_data.get(data_key, "")
                leads.append(lead)

                print(f"    + {name} ({category}) - {address}")
              except Exception as place_err:
                import traceback
                print(f"  WARNING: Skipping place due to error: {place_err}")
                print(f"  Traceback: {traceback.format_exc()}")
                continue

            # Mark scan as completed
            scan_key = (round(lat, 5), round(lng, 5), search_term)
            completed_scans.add(scan_key)

            # Periodic save
            if stats["leads_generated"] > 0 and stats["leads_generated"] % SAVE_INTERVAL == 0:
                save_results(leads, profile, paths)
                progress["seen_place_ids"] = list(seen_place_ids)
                progress["completed_scans"] = [list(s) for s in completed_scans]
                save_progress(progress, paths)

    except Exception as e:
        import traceback
        print(f"\n⚠️ Scan interrupted by error: {type(e).__name__}: {e}")
        print(f"  Full traceback:\n{traceback.format_exc()}")
        print("Saving any leads collected so far...")

    # Final save
    save_results(leads, profile, paths)
    progress["seen_place_ids"] = list(seen_place_ids)
    progress["completed_scans"] = [list(s) for s in completed_scans]
    save_progress(progress, paths)

    # Summary
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("LEAD GENERATION COMPLETE")
    print("=" * 60)
    print(f"  Profile: {profile['name']}")
    print(f"  Time elapsed: {elapsed / 60:.1f} minutes")
    print(f"  API calls made: {stats['api_calls']}")
    print(f"  Businesses checked: {stats['businesses_found']}")
    print(f"  Chains filtered out: {stats['chains_filtered']}")
    print(f"  Duplicates skipped: {stats['duplicates_skipped']}")
    print(f"  Leads generated: {stats['leads_generated']}")
    print()
    print(f"Leads saved to: {paths['csv']}")

    # Breakdown by category
    if leads:
        print()
        print("Leads by category:")
        cat_key = None
        for col_header, data_key in profile["csv_columns"]:
            if data_key == "category":
                cat_key = col_header
                break
        if cat_key:
            category_counts = {}
            for lead in leads:
                c = lead.get(cat_key, "Unknown")
                category_counts[c] = category_counts.get(c, 0) + 1
            for c, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                print(f"  {c}: {count}")


# =============================================================================
# Dry Run
# =============================================================================

def dry_run(profile):
    """Show search plan without making API calls."""
    grid_extent = profile.get("grid_extent", 1500)
    grid_step = profile.get("grid_step", 400)

    sample_area = profile["search_areas"][0]
    grid_points = generate_grid_points(sample_area[0], sample_area[1], grid_extent, grid_step)
    points_per_area = len(grid_points)

    num_areas = len(profile["search_areas"])
    num_primary = len(profile.get("primary_searches", []))
    num_secondary = len(profile.get("secondary_searches", []))
    total_searches = num_areas * points_per_area * (num_primary + num_secondary)

    print("=" * 60)
    print("STEPUP AI - LEAD GENERATION TOOL (DRY RUN)")
    print("=" * 60)
    print()
    print(f"Profile:           {profile['name']}")
    print(f"Description:       {profile['description']}")
    print(f"Business type:     {profile.get('included_type', 'Any (text search)')}")
    print(f"Website filter:    {profile['website_filter']}")
    print(f"Location:          {profile['location_name']}")
    print()
    print(f"Search areas:      {num_areas}")
    print(f"Grid points/area:  {points_per_area}")
    print(f"Primary terms:     {num_primary}")
    print(f"Secondary terms:   {num_secondary}")
    print()
    print(f"Total grid searches:     {total_searches:,}")
    print(f"Est. Text Search calls:  {total_searches:,}")
    print(f"Est. Detail calls:       varies (unique places found)")
    print()

    # Cost estimate
    search_cost = (total_searches / 1000) * 32
    detail_estimate = total_searches * 0.3
    detail_cost = (detail_estimate / 1000) * 17
    total_cost = search_cost + detail_cost
    print(f"Estimated API cost:      ${total_cost:.0f}")
    print(f"  (Google gives $200/month free credit)")
    if total_cost > 200:
        print(f"  WARNING: Estimated cost exceeds free tier by ${total_cost - 200:.0f}")
    else:
        print(f"  Within free tier ({total_cost / 200 * 100:.0f}% of $200 credit)")
    print()

    print("Primary search terms:")
    for term in profile.get("primary_searches", []):
        print(f"  - {term}")
    print()
    print("Secondary search terms:")
    for term in profile.get("secondary_searches", []):
        print(f"  - {term}")
    print()
    print("First 5 search areas:")
    for lat, lng, label in profile["search_areas"][:5]:
        print(f"  - {label} ({lat:.4f}, {lng:.4f})")
    if num_areas > 5:
        print(f"  ... and {num_areas - 5} more")


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="StepUP AI Lead Generation Tool",
        epilog="Create new profiles by copying profiles/_template.py",
    )
    parser.add_argument(
        "--profile", "-p", required=True,
        help="Name of search profile (e.g., restaurants_paris, vtc_idf)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show search plan and cost estimate without making API calls",
    )

    args = parser.parse_args()
    profile = load_profile(args.profile)

    if args.dry_run:
        dry_run(profile)
    else:
        generate_leads(profile)
