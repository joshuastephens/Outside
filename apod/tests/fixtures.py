"""Canned upstream payloads.

The video payload is NASA's own documented example response; the image payload
adds the `hdurl` and `copyright` fields that NASA includes on some days and
omits on others.
"""

VIDEO_PAYLOAD = {
    "date": "2026-09-09",
    "explanation": (
        "Is this star winking at us? The central object in today's animation is "
        "not one but two stars. XZ Andromedae, indicated by the bold lines, is "
        "an Algol-type eclipsing binary with a nearly edge-on orbit from "
        "Earth's perspective."
    ),
    "media_type": "video",
    "service_version": "v1",
    "title": "Witness XZ Andromedae Wink",
    "url": "https://apod.nasa.gov/apod/image/2609/xz_and.mp4",
}

# Note: no `hdurl`, no `copyright` -- the minimal shape NASA can return.
MINIMAL_PAYLOAD = dict(VIDEO_PAYLOAD)


def image_payload(date="2024-05-01"):
    """A payload with every optional field populated."""
    return {
        "date": date,
        "explanation": "A spiral galaxy seen nearly face-on.",
        "hdurl": "https://apod.nasa.gov/apod/image/2405/galaxy_hd.jpg",
        "media_type": "image",
        "service_version": "v1",
        "title": "Messier 101",
        "url": "https://apod.nasa.gov/apod/image/2405/galaxy.jpg",
        "copyright": "Some Astrophotographer",
    }


WIKIPEDIA_SEARCH_RESPONSE = {
    "batchcomplete": "",
    "query": {
        "search": [
            {"ns": 0, "title": "XZ Andromedae", "pageid": 12345, "snippet": "..."}
        ]
    },
}

WIKIPEDIA_EXTRACT_RESPONSE = {
    "batchcomplete": "",
    "query": {
        "pages": {
            "12345": {
                "pageid": 12345,
                "ns": 0,
                "title": "XZ Andromedae",
                "fullurl": "https://en.wikipedia.org/wiki/XZ_Andromedae",
                "extract": (
                    "XZ Andromedae is an Algol-type eclipsing binary star "
                    "system in the constellation Andromeda."
                ),
            }
        }
    },
}

WIKIPEDIA_EMPTY_SEARCH_RESPONSE = {"batchcomplete": "", "query": {"search": []}}


def search_response(*titles):
    """Build a MediaWiki `list=search` response for the given page titles."""
    return {
        "batchcomplete": "",
        "query": {
            "search": [
                {"ns": 0, "title": title, "pageid": 1000 + index, "snippet": "..."}
                for index, title in enumerate(titles)
            ]
        },
    }


def extract_response(title, extract, pageid=12345, fullurl=None):
    """Build a MediaWiki `prop=extracts` response for one page."""
    slug = title.replace(" ", "_")
    return {
        "batchcomplete": "",
        "query": {
            "pages": {
                str(pageid): {
                    "pageid": pageid,
                    "ns": 0,
                    "title": title,
                    "fullurl": fullurl or f"https://en.wikipedia.org/wiki/{slug}",
                    "extract": extract,
                }
            }
        },
    }


# The five real APOD titles that the unscored cascade matched confidently and
# wrongly, with the candidates live MediaWiki actually returns for each.
BAD_MATCH_CANDIDATES = {
    "Pink Aurora over Crater Lake": [
        "Mono Lake",
        "Atmosphere of Mars",
        "List of natural history museums in the United States",
        "Mars",
        "Earth",
    ],
    "Comet NEOWISE over Lebanon": ["Yara Zgheib"],
    "Colorful Clouds Over Sicily": [
        "Equestrian Portrait of Joachim Murat, King of Naples",
        "J. Paul Getty Museum",
        "Zouave",
        "Agate",
        "List of Super Wings episodes",
    ],
    "Ice Halos over Bavaria": [
        "Rainbow",
        "Deaths in September 2023",
        "Standard German",
        "White",
        "List of country-name etymologies",
    ],
    "Saturn at Night": [
        "Saturn",
        "Perry Saturn",
        "Night Warriors: Darkstalkers' Revenge",
        "Night Striker",
        "Saturn V",
    ],
}
