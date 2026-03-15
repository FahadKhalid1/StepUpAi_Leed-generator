# =============================================================================
# StepUP AI - Lead Generation Profile
# RESTAURANTS IN PARIS (without websites)
# =============================================================================

PROFILE = {
    # === Identity ===
    "name": "restaurants_paris",
    "description": "Independent restaurants in Paris without websites",

    # === Business Type ===
    "included_type": "restaurant",       # Google Places type filter
    "website_filter": "no_website",      # Only find restaurants WITHOUT a website

    # === Search Terms (Priority) ===
    "primary_searches": [
        "indian restaurant",
        "pakistani restaurant",
        "turkish restaurant",
        "bangladeshi restaurant",
        "moroccan restaurant",
        "arabic restaurant",
        "middle eastern restaurant",
        "lebanese restaurant",
        "afghan restaurant",
        "halal restaurant",
        "kebab restaurant",
        "tunisian restaurant",
        "algerian restaurant",
        "persian restaurant",
        "syrian restaurant",
    ],

    # === Search Terms (Secondary) ===
    "secondary_searches": [
        "restaurant",
    ],

    # === Location ===
    "location_name": "Paris",
    "language_code": "fr",
    "search_areas": [
        # Start with 17th
        (48.8836, 2.3133, "Paris 17e"),
        # Then the rest
        (48.8607, 2.3472, "Paris 1er"),
        (48.8670, 2.3410, "Paris 2e"),
        (48.8632, 2.3592, "Paris 3e"),
        (48.8543, 2.3615, "Paris 4e"),
        (48.8462, 2.3498, "Paris 5e"),
        (48.8499, 2.3322, "Paris 6e"),
        (48.8566, 2.3150, "Paris 7e"),
        (48.8744, 2.3106, "Paris 8e"),
        (48.8768, 2.3381, "Paris 9e"),
        (48.8761, 2.3607, "Paris 10e"),
        (48.8589, 2.3813, "Paris 11e"),
        (48.8405, 2.3882, "Paris 12e"),
        (48.8322, 2.3561, "Paris 13e"),
        (48.8312, 2.3265, "Paris 14e"),
        (48.8406, 2.2988, "Paris 15e"),
        (48.8630, 2.2753, "Paris 16e"),
        (48.8924, 2.3444, "Paris 18e"),
        (48.8871, 2.3822, "Paris 19e"),
        (48.8633, 2.3985, "Paris 20e"),
    ],
    "search_radius": 500,
    "grid_step": 400,
    "grid_extent": 1500,

    # === Chain Blocklist (excluded from results) ===
    "chain_blocklist": [
        # Global fast food
        "mcdonald", "burger king", "kfc", "kentucky fried", "subway",
        "domino", "pizza hut", "taco bell", "wendy", "five guys",
        "popeyes", "chick-fil-a", "papa john", "little caesars",
        "jack in the box", "sonic drive", "arby",
        # European/French chains
        "quick", "flunch", "hippopotamus", "buffalo grill", "courtepaille",
        "del arte", "pizza del arte", "la pataterie", "léon de bruxelles",
        "leon de bruxelles", "bistro romain", "tablapizza", "la boucherie",
        "poivre rouge", "class croute", "class'croute", "brioche dorée",
        "brioche doree", "paul", "pomme de pain",
        # Kebab/fast food chains
        "o'tacos", "otacos", "bagelstein", "eat sushi", "sushi shop",
        "planet sushi", "exki", "cojean", "prêt à manger", "pret a manger",
        "starbucks", "costa coffee", "colombus café", "columbus cafe",
        # Burger chains
        "big fernand", "blend hamburger",
        # Pizza chains
        "dominos", "papa johns", "telepizza",
        # Asian fast food chains
        "wok to walk", "pitaya", "bao family",
    ],

    # === Category Classification ===
    "category_keywords": {
        "Indian": ["indian", "tandoori", "curry", "masala", "biryani", "dosa", "thali", "paneer"],
        "Pakistani": ["pakistani", "lahori", "karahi", "nihari"],
        "Turkish": ["turkish", "turc", "kebab", "döner", "doner", "pide", "lahmacun", "ocakbasi"],
        "Bangladeshi": ["bangladeshi", "bengali", "bangla"],
        "Moroccan": ["moroccan", "marocain", "couscous", "tajine", "tagine"],
        "Arabic": ["arabic", "arabe", "shawarma", "falafel", "mezzé", "mezze"],
        "Lebanese": ["lebanese", "libanais"],
        "Afghan": ["afghan"],
        "Middle Eastern": ["middle eastern", "moyen orient", "oriental"],
        "Tunisian": ["tunisian", "tunisien"],
        "Algerian": ["algerian", "algérien", "algerien"],
        "Persian": ["persian", "iranian", "persan", "iranien"],
        "Syrian": ["syrian", "syrien"],
        "Halal": ["halal"],
    },

    # === District Extraction ===
    "district_pattern": r"750(\d{2})",
    "district_format": "Paris {num}e",       # {num} gets replaced; 1 → "er" handled in code
    "district_fallback_check": "paris",
    "district_fallback_label": "Paris (arrondissement unknown)",
    "district_outside_label": "Outside Paris",

    # === CSV Output Columns ===
    # Each tuple: (CSV column header, internal data key)
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
