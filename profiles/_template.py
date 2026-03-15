# =============================================================================
# StepUP AI - Lead Generation Profile TEMPLATE
#
# HOW TO USE:
# 1. Copy this file to profiles/my_search_name.py
# 2. Fill in the PROFILE dict below
# 3. Run: python lead_generator.py --profile my_search_name
# 4. Preview first: python lead_generator.py --profile my_search_name --dry-run
# =============================================================================

PROFILE = {
    # === Identity ===
    "name": "my_search_name",                     # Must match filename (without .py)
    "description": "Short description of this search",

    # === Business Type ===
    # Google Places type to filter by. Set to None for text-search only.
    # Common types: "restaurant", "hair_care", "car_repair", "dentist",
    #               "gym", "bakery", "pharmacy", "hotel"
    # Full list: https://developers.google.com/maps/documentation/places/web-service/place-types
    "included_type": "restaurant",

    # Website filter: "no_website" = only businesses WITHOUT a site
    #                 "has_website" = only businesses WITH a site
    #                 "all" = keep all businesses regardless
    "website_filter": "no_website",

    # === Search Terms ===
    # Primary searches run first (higher priority in results)
    "primary_searches": [
        "search term 1",
        "search term 2",
    ],

    # Secondary searches run after primary (lower priority)
    "secondary_searches": [
        "general search term",
    ],

    # === Location ===
    # Location name appended to every search query (e.g., "pizza restaurant Paris")
    "location_name": "Paris",

    # Language for results
    "language_code": "fr",

    # Search area centers: list of (latitude, longitude, "label") tuples
    # You can define these manually or generate from a bounding box
    "search_areas": [
        (48.8566, 2.3522, "City Center"),
    ],

    # Grid parameters (in meters)
    "search_radius": 500,       # Search radius around each grid point
    "grid_step": 400,           # Distance between grid points (less than radius for overlap)
    "grid_extent": 1500,        # How far from each area center to generate grid points

    # === Filtering ===
    # Business names containing any of these strings are excluded
    "chain_blocklist": [
        "mcdonald",
        "starbucks",
    ],

    # === Category Classification (optional) ===
    # Keywords to auto-classify businesses into categories
    # Set to {} or remove to skip classification
    "category_keywords": {
        "Category A": ["keyword1", "keyword2"],
        "Category B": ["keyword3", "keyword4"],
    },

    # === District Extraction (optional) ===
    # Regex to extract a district/postal code from the address
    # The first capture group is used
    "district_pattern": r"(\d{5})",      # Matches 5-digit French postal codes

    # Format string: {num} is replaced with the captured number
    # Special: for Paris arrondissements use "Paris {num}e"
    "district_format": "{num:05d}",

    # If address contains this string but no pattern match, use fallback label
    "district_fallback_check": "paris",
    "district_fallback_label": "Unknown area",
    "district_outside_label": "Other",

    # === CSV Output Columns ===
    # Each tuple: ("Column Header in CSV", "internal_data_key")
    #
    # Available data keys:
    #   displayName              - Business name
    #   category                 - Auto-classified category
    #   priority                 - "Primary" or "Secondary"
    #   formattedAddress         - Full address
    #   district                 - Extracted district/postal code
    #   internationalPhoneNumber - Phone number
    #   websiteUri               - Website URL (useful when website_filter = "all")
    #   rating                   - Google rating (1-5)
    #   userRatingCount          - Number of reviews
    #   googleMapsUri            - Google Maps link
    #   place_id                 - Google Place ID (for deduplication)
    "csv_columns": [
        ("Business Name", "displayName"),
        ("Category", "category"),
        ("Priority", "priority"),
        ("Address", "formattedAddress"),
        ("District", "district"),
        ("Phone Number", "internationalPhoneNumber"),
        ("Website", "websiteUri"),
        ("Rating", "rating"),
        ("Total Reviews", "userRatingCount"),
        ("Google Maps URL", "googleMapsUri"),
        ("Place ID", "place_id"),
    ],
}
