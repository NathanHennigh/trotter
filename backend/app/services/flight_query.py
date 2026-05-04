"""
Flight email detection query for Gmail API.

This module builds the Gmail search query used to find flight-related emails.
Edit the lists below to add/remove keywords or sender domains.

Gmail query docs: https://support.google.com/mail/answer/7190
"""

# ─── Subject / body keywords ──────────────────────────────────────────────────
# Broad terms that appear in flight confirmation emails regardless of airline.
# Gmail searches subject AND body when you use bare keywords (no subject: prefix).
SUBJECT_KEYWORDS: list[str] = [
    # English — booking & confirmation
    "boarding pass",
    "e-ticket",
    "eticket",
    "electronic ticket",
    "ticket number",
    "itinerary",
    "flight confirmation",
    "flight receipt",
    "flight booking",
    "flight details",
    "flight change",
    "flight update",
    "flight status",
    "flight delay",
    "flight cancelled",
    "flight canceled",
    "your booking",
    "booking confirmation",
    "booking reference",
    "booking code",
    "reservation confirmed",
    "reservation confirmation",
    "your reservation",
    "travel confirmation",
    "travel itinerary",
    "trip confirmation",
    "trip itinerary",
    "trip details",
    "trip receipt",
    "your trip",
    "your upcoming trip",
    "your flight",
    "your ticket",
    "ticket confirmation",
    "ticket receipt",
    "passenger receipt",
    "order confirmation",
    "purchase confirmation",
    "record locator",
    "confirmation code",
    "PNR",

    # Seat & boarding
    "boarding group",
    "boarding zone",
    "boarding priority",
    "boarding begins",
    "boarding time",
    "boarding starts",
    "priority boarding",
    "seat assignment",
    "seat change",
    "seat confirmation",
    "upgrade confirmed",
    "upgrade request",

    # Gate & departure
    "departure gate",
    "departure reminder",
    "arrival gate",
    "gate change",
    "schedule change",
    "updated itinerary",
    "important information about your trip",
    "final boarding call",

    # Check-in
    "check-in is now open",
    "online check-in",
    "check in for your flight",
    "download your boarding pass",
    "mobile boarding pass",
    "bag drop",
    "baggage drop",
    "ready to check in",
    "time to check in",
    "check in now",

    # Management
    "manage your trip",
    "manage your booking",
    "view your itinerary",

    # Spanish
    "tarjeta de embarque",
    "confirmación de vuelo",
    "tu vuelo",

    # French
    "carte d'embarquement",
    "confirmation de vol",
    "votre vol",

    # German
    "Bordkarte",
    "Flugbestätigung",
    "Ihre Buchung",

    # Portuguese
    "cartão de embarque",
    "confirmação de voo",

    # Italian
    "carta d'imbarco",
    "conferma del volo",

    # Japanese
    "搭乗券",
    "予約確認",
]

# ─── Known sender domains ─────────────────────────────────────────────────────
# Emails FROM these domains are almost certainly travel-related.
SENDER_DOMAINS: list[str] = [
    # ── US carriers ──────────────────────────────────────────────
    "aa.com",                   # American Airlines
    "united.com",               # United Airlines
    "delta.com",                # Delta Air Lines
    "southwest.com",            # Southwest Airlines
    "jetblue.com",              # JetBlue
    "spirit.com",               # Spirit Airlines
    "frontierairlines.com",     # Frontier Airlines
    "alaskaair.com",            # Alaska Airlines
    "hawaiianairlines.com",     # Hawaiian Airlines
    "allegiantair.com",         # Allegiant Air
    "suncountry.com",           # Sun Country Airlines
    "flybreeze.com",            # Breeze Airways
    "aveloair.com",             # Avelo Airlines
    "jsx.com",                  # JSX
    "contourairlines.com",      # Contour Airlines
    "capeair.com",              # Cape Air
    "silverairways.com",        # Silver Airways
    "boutiqueair.com",          # Boutique Air

    # ── OTAs & booking platforms ──────────────────────────────────
    "trip.com",
    "hopper.com",
    "studentuniverse.com",
    "travelperk.com",
    "cleartrip.com",
    "gotogate.com",
    "budgetair.com",
    "mytrip.com",
    "tripmonster.com",
    "capitalonetravel.com",
    "capitalonebooking.com",
    "chase.com",                # Chase Ultimate Rewards travel
    "ultimaterewards.com",
    "amextravel.com",
    "americanexpress.com",
    "citi.com",
    "thankyou.com",             # Citi ThankYou travel portal
    "calendar.google.com",
    "googletravel.com",
    "apple.com",                # Apple Wallet boarding passes
    "travelbank.com",
    "rockettravel.com",
    "cxloyalty.com",
    "arrivia.com",
    "switchfly.com",
    "bakkt.com",

    # ── International carriers ────────────────────────────────────
    "britishairways.com",       # British Airways
    "ba.com",
    "virginatlantic.com",       # Virgin Atlantic
    "lufthansa.com",            # Lufthansa
    "airfrance.com",            # Air France
    "klm.com",                  # KLM
    "emirates.com",             # Emirates
    "etihad.com",               # Etihad
    "qatarairways.com",         # Qatar Airways
    "singaporeair.com",         # Singapore Airlines
    "cathaypacific.com",        # Cathay Pacific
    "ana.co.jp",                # ANA
    "jal.com",                  # Japan Airlines
    "qantas.com",               # Qantas
    "aircanada.com",            # Air Canada
    "aeromexico.com",           # Aeromexico
    "iberia.com",               # Iberia
    "tur.com.tr",               # Turkish Airlines
    "turkishairlines.com",
    "swiss.com",                # Swiss Air
    "austrian.com",             # Austrian Airlines
    "brusselsairlines.com",     # Brussels Airlines
    "ryanair.com",              # Ryanair
    "easyjet.com",              # easyJet
    "wizzair.com",              # Wizz Air
    "vueling.com",              # Vueling
    "transavia.com",            # Transavia
    "norwegian.com",            # Norwegian Air
    "norwegian.no",
    "finnair.com",              # Finnair
    "lot.com",                  # LOT Polish Airlines
    "tarom.ro",                 # TAROM
    "airserbia.com",            # Air Serbia
    "aeroflot.ru",              # Aeroflot
    "s7.ru",                    # S7 Airlines
    "airasia.com",              # AirAsia
    "lionair.co.id",            # Lion Air
    "batikair.com",             # Batik Air
    "cebupacificair.com",       # Cebu Pacific
    "philippineairlines.com",   # Philippine Airlines
    "garuda-indonesia.com",     # Garuda Indonesia
    "indigo.in",                # IndiGo
    "airindia.in",              # Air India
    "vistara.com",              # Vistara
    "spicejet.com",             # SpiceJet
    "goair.in",                 # Go Air
    "flyadeal.com",             # flyadeal
    "saudia.com",               # Saudia
    "flydubai.com",             # flydubai
    "airarabia.com",            # Air Arabia
    "israelairlines.com",       # El Al
    "elal.co.il",
    "tapairportugal.com",       # TAP Air Portugal
    "flytap.com",
    "aerlingus.com",            # Aer Lingus
    "icelandair.com",           # Icelandair
    "sas.se",                   # SAS
    "sas.no",
    "sas.dk",
    "airbaltic.com",            # airBaltic
    "flyscoot.com",             # Scoot
    "thaiairways.com",          # Thai Airways
    "evaair.com",               # EVA Air
    "china-airlines.com",       # China Airlines
    "koreanair.com",            # Korean Air
    "flyasiana.com",            # Asiana
    "malaysiaairlines.com",     # Malaysia Airlines
    "vietnamairlines.com",      # Vietnam Airlines
    "ethiopianairlines.com",    # Ethiopian Airlines
    "kenya-airways.com",        # Kenya Airways
    "rwandair.com",             # RwandAir
    "royalairmaroc.com",        # Royal Air Maroc
    "egyptair.com",             # Egyptair
    "latamairlines.com",        # LATAM
    "avianca.com",              # Avianca
    "copaair.com",              # Copa
    "voeazul.com.br",           # Azul
    "voegol.com.br",            # GOL
    "flybondi.com",             # Flybondi
    "jetstar.com",              # Jetstar
    "virginaustralia.com",      # Virgin Australia
    "airnewzealand.com",        # Air New Zealand

    # ── OTAs & booking platforms (continued) ─────────────────────
    "expedia.com",
    "hotels.com",
    "hotwire.com",
    "orbitz.com",
    "travelocity.com",
    "priceline.com",
    "kayak.com",
    "booking.com",
    "agoda.com",
    "kiwi.com",
    "skyscanner.net",
    "momondo.com",
    "cheapflights.com",
    "cheapoair.com",
    "onetravel.com",
    "vayama.com",
    "justfly.com",
    "google.com",               # Google Flights order receipts
    "tripadvisor.com",
    "lastminute.com",
    "opodo.com",
    "edreams.com",
    "bravofly.com",
    "flighthub.com",
    "travelgenio.com",
    "smartfares.com",
    "skiplagged.com",
    "alternativeairlines.com",
    "airwander.com",
    "tripsta.com",
    "fareportal.com",

    # ── Corporate travel tools ────────────────────────────────────
    "concur.com",
    "egencia.com",
    "amexgbt.com",
    "bcdtravel.com",
    "carlsonwagonlit.com",
    "navan.com",                # TripActions / Navan
    "tripactions.com",
    "spotnana.com",
    "deem.com",
    "travelctm.com",
    "reedmackay.com",
    "travelandleisureco.com",

    # ── Loyalty & travel apps ─────────────────────────────────────
    "tripit.com",
    "awardwallet.com",
    "points.com",
    "mileiq.com",
    "flightaware.com",
    "flightradar24.com",
    "seatguru.com",
    "upgradedpoints.com",
    "thepointsguy.com",
    "rocketmiles.com",
    "aadvantageeshopping.com",
    "mileageplus.com",
    "skymiles.com",
    "rapidrewards.com",
    "marriott.com",
    "hilton.com",
    "hyatt.com",
    "ihg.com",
]


def build_gmail_query() -> str:
    """
    Build a Gmail search query string combining keyword and sender-domain filters.

    Returns an OR of:
      - subject/body keyword terms
      - from: sender domain terms

    The result is a single string you can paste into the Gmail search bar to preview.
    """
    keyword_parts = " OR ".join(f'"{kw}"' for kw in SUBJECT_KEYWORDS)
    domain_parts  = " OR ".join(f"from:{d}" for d in SENDER_DOMAINS)
    return f"({keyword_parts}) OR ({domain_parts})"


if __name__ == "__main__":
    q = build_gmail_query()
    print(f"Query length: {len(q)} chars\n")
    print(q)
