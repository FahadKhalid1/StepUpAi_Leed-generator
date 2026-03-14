# =============================================================================
# StepUP AI - Lead Generation Profile
# VTC / CHAUFFEUR COMPANIES in Paris & Ile-de-France
# =============================================================================

import math


def _generate_idf_grid():
    """Generate search area centers covering Ile-de-France from a bounding box.

    Ile-de-France departments:
    - 75: Paris
    - 92: Hauts-de-Seine (petite couronne)
    - 93: Seine-Saint-Denis (petite couronne)
    - 94: Val-de-Marne (petite couronne)
    - 77: Seine-et-Marne (grande couronne)
    - 78: Yvelines (grande couronne)
    - 91: Essonne (grande couronne)
    - 95: Val-d'Oise (grande couronne)
    """
    # Ile-de-France approximate bounding box
    min_lat, max_lat = 48.12, 49.24
    min_lng, max_lng = 1.45, 3.56
    step_km = 10  # 10km spacing between area centers

    lat_step = step_km / 111.32
    lng_step = step_km / (111.32 * math.cos(math.radians(48.68)))

    areas = []
    lat = min_lat
    idx = 0
    while lat <= max_lat:
        lng = min_lng
        while lng <= max_lng:
            areas.append((lat, lng, f"IDF-zone-{idx}"))
            lng += lng_step
            idx += 1
        lat += lat_step
    return areas


PROFILE = {
    # === Identity ===
    "name": "vtc_idf",
    "description": "VTC and chauffeur companies in Paris & Ile-de-France",

    # === Business Type ===
    "included_type": None,               # No specific Google type for VTC; text search only
    "website_filter": "all",             # Find ALL companies (with AND without websites)

    # === Search Terms (Priority) ===
    "primary_searches": [
        "VTC",
        "chauffeur privé",
        "transport VTC",
        "voiture de tourisme avec chauffeur",
        "chauffeur VTC",
    ],

    # === Search Terms (Secondary) ===
    "secondary_searches": [
        "chauffeur",
        "transport privé",
        "limousine service",
        "navette aéroport",
        "transfer aéroport",
    ],

    # === Location ===
    "location_name": "Ile-de-France",
    "language_code": "fr",
    "search_areas": _generate_idf_grid(),
    "search_radius": 3000,              # Larger radius for suburban/rural areas
    "grid_step": 2500,
    "grid_extent": 5000,

    # === Chain / Platform Blocklist ===
    "chain_blocklist": [
        "uber", "bolt", "heetch", "freenow", "free now",
        "marcel", "blablacar", "bla bla car",
        "kapten", "lyft", "didi", "grab",
        "g7",  # Taxi platform, not VTC
        "taxi",  # Filter out taxi companies (not VTC)
    ],

    # === Category Classification ===
    "category_keywords": {
        "VTC": ["vtc", "voiture de tourisme"],
        "Chauffeur Privé": ["chauffeur privé", "chauffeur prive", "private driver", "chauffeur de maitre"],
        "Limousine": ["limousine", "limo", "berline"],
        "Navette": ["navette", "shuttle", "transfert", "transfer"],
        "Transport": ["transport privé", "transport prive"],
    },

    # === District Extraction ===
    "district_pattern": r"(\d{5})",          # Any 5-digit French postal code
    "district_format": "{num:05d}",          # Return the full postal code
    "district_fallback_check": "paris",
    "district_fallback_label": "Paris area",
    "district_outside_label": "Ile-de-France",

    # === CSV Output Columns ===
    "csv_columns": [
        ("Business Name", "displayName"),
        ("Category", "category"),
        ("Priority", "priority"),
        ("Address", "formattedAddress"),
        ("Postal Code", "district"),
        ("Phone Number", "internationalPhoneNumber"),
        ("Website", "websiteUri"),            # VTC profile INCLUDES website info
        ("Rating", "rating"),
        ("Total Reviews", "userRatingCount"),
        ("Google Maps URL", "googleMapsUri"),
        ("Place ID", "place_id"),
    ],
}
