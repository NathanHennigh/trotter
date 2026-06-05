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
LOW_VALUE_FULL_HISTORY_KEYWORDS: set[str] = {
    # These terms produced no unique corpus recall and/or high mailbox noise.
    # Keep them available to broad/background query builders, but do not use
    # them in the full-history incremental_precise tier.
    "Bordkarte",
    "Ihre Buchung",
    "boarding starts",
    "boarding zone",
    "booking code",
    "carta d'imbarco",
    "carte d'embarquement",
    "conferma del volo",
    "confirmation de vol",
    "departure reminder",
    "final boarding call",
    "important information about your trip",
    "order confirmation",
    "passenger receipt",
    "purchase confirmation",
    "ready to check in",
    "reservation confirmed",
    "seat change",
    "seat confirmation",
    "tarjeta de embarque",
    "ticket confirmation",
    "travel itinerary",
    "trip itinerary",
    "tu vuelo",
    "upgrade confirmed",
    "upgrade request",
    "votre vol",
}

PRECISE_SUBJECT_KEYWORDS: list[str] = [
    keyword for keyword in SUBJECT_KEYWORDS if keyword not in LOW_VALUE_FULL_HISTORY_KEYWORDS
]

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


# Sender categories for the fast sender-first importer. Keep the legacy
# SENDER_DOMAINS list above for backwards-compatible broad query builders.
HIGH_CONFIDENCE_FLIGHT_SENDERS: list[str] = [
    "aa.com",
    "info.email.aa.com",
    "notify.email.aa.com",
    "mail.ms.aa.com",
    "non-aadvantage.mail.ms.aa.com",
    "united.com",
    "delta.com",
    "t.delta.com",
    "e.delta.com",
    "n.delta.com",
    "southwest.com",
    "ifly.southwest.com",
    "iluv.southwest.com",
    "mbp.southwest.com",
    "jetblue.com",
    "spirit.com",
    "fly.spirit-airlines.com",
    "flightupdate.spirit-airlines.com",
    "frontierairlines.com",
    "emails.flyfrontier.com",
    "reservation.flyfrontier.com",
    "alaskaair.com",
    "hawaiianairlines.com",
    "allegiantair.com",
    "e.allegiant.com",
    "t.allegiant.com",
    "suncountry.com",
    "britishairways.com",
    "ba.com",
    "virginatlantic.com",
    "lufthansa.com",
    "airfrance.com",
    "klm.com",
    "emirates.com",
    "emirates.email",
    "etihad.com",
    "qatarairways.com",
    "singaporeair.com",
    "cathaypacific.com",
    "ana.co.jp",
    "jal.com",
    "qantas.com",
    "aircanada.com",
    "aeromexico.com",
    "itineraries.aeromexico.com",
    "iberia.com",
    "comunicaciones.iberia.com",
    "turkishairlines.com",
    "swiss.com",
    "austrian.com",
    "brusselsairlines.com",
    "ryanair.com",
    "easyjet.com",
    "wizzair.com",
    "vueling.com",
    "transavia.com",
    "norwegian.com",
    "norwegian.no",
    "finnair.com",
    "lot.com",
    "airasia.com",
    "booking.airasia.com",
    "evaair.com",
    "tapairportugal.com",
    "flytap.com",
    "aerlingus.com",
    "icelandair.com",
    "sas.se",
    "sas.no",
    "sas.dk",
    "flyscoot.com",
    "ethiopianairlines.com",
    "kenya-airways.com",
    "royalairmaroc.com",
    "latamairlines.com",
    "avianca.com",
    "copaair.com",
]

OTA_FLIGHT_SENDERS: list[str] = [
    "studentuniverse.com",
    "trip.com",
    "hopper.com",
    "travelperk.com",
    "cleartrip.com",
    "gotogate.com",
    "budgetair.com",
    "mytrip.com",
    "capitalonetravel.com",
    "capitalonebooking.com",
    "ultimaterewards.com",
    "amextravel.com",
    "googletravel.com",
    "travelbank.com",
    "capitalonebooking.com",
    "chasetravel.com",
    "expediamail.com",
    "gondola.ai",
    "expedia.com",
    "orbitz.com",
    "travelocity.com",
    "priceline.com",
    "kiwi.com",
    "cheapoair.com",
    "onetravel.com",
    "justfly.com",
    "flighthub.com",
    "yourbooking.qantas.com.au",
    "concur.com",
    "egencia.com",
    "amexgbt.com",
    "bcdtravel.com",
    "navan.com",
    "tripactions.com",
]

NOISY_TRAVEL_SENDERS: list[str] = [
    "google.com",
    "apple.com",
    "chase.com",
    "americanexpress.com",
    "citi.com",
    "thankyou.com",
    "booking.com",
    "agoda.com",
    "hotels.com",
    "hotwire.com",
    "marriott.com",
    "hilton.com",
    "hyatt.com",
    "ihg.com",
    "tripadvisor.com",
    "kayak.com",
    "skyscanner.net",
    "momondo.com",
    "flightaware.com",
    "flightradar24.com",
    "seatguru.com",
    "thepointsguy.com",
    "upgradedpoints.com",
    "aadvantageeshopping.com",
    "mileageplus.com",
    "skymiles.com",
    "rapidrewards.com",
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
