# Key: incorrect ref from API, Value: correct ref to use.
DICT_REF_REPLACEMENTS = {
}

# A set of {form}_{item} keys to completely ignore
FORMS_TO_IGNORE = {
}

# A set of entries to completely ignore
IGNORED_DICT_REFS = {
}

# Maps a word to a different word that should be used for the API query
ANALYSIS_ALIASES = {
}

FULL_OVERRIDES = {
}

FORMS = {
    "fas_0_0": {
        "partOfSpeech": "noun",
        "gender": "neuter",
        "number": "singular",
        "case": "nominative/accusative",
    },
    "circumeunti_0_0": {
        "gender": "masculine/feminine/neuter",
    },
    "eunti_0_0": {
        "gender": "masculine/feminine/neuter",
    },
    "altiore_1_0": {
        "gender": "masculine/feminine/neuter",
    },
    "altiore_0_0": {
        "gender": "masculine/feminine/neuter",
    },
    "plus_0_0": {
        "gender": "neuter",
    },
    "plus_0_1": {
        "gender": "neuter",
    },
    "satis_1_1": {
        "partOfSpeech": "adjective",
        "gender": None,
    },
    "ferret_0_0": {
        "verbForm": "subjunctive",
        "partOfSpeech": "verb",
    },
    "ferrem_0_0": {
        "verbForm": "subjunctive",
        "partOfSpeech": "verb",
    },
    "referret_0_0": {
        "verbForm": "subjunctive",
        "partOfSpeech": "verb",
    },
    "referret_0_1": {
        "verbForm": "subjunctive",
        "partOfSpeech": "verb",
    },
    "constantior_0_0": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "constantior_0_1": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "constantior_0_2": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "constantior_0_3": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "diligentius_1_1": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "diligentius_1_2": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "diligentius_1_3": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "iactantiorem_0_0": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "iactantiorem_0_1": {
        "declension": "3rd",
        "partOfSpeech": "adjective",
        "segmentsInfo": "ior, -ius",
    },
    "celeri_0_0": {
        "segmentsInfo": ", -is, -e",
    },
    "celeri_0_1": {
        "segmentsInfo": ", -is, -e",
    },
    "celeri_0_2": {
        "segmentsInfo": ", -is, -e",
    },
}

NOT_WANTED_INFLECTIONS = {
    # keep exclusively to the last index just in case
    "deflesset_0_1",
}

# Whitelist (many errors in morpheus with fake adverbs)
TRUE_ADVERB_FORMS = {
    "brevi",
    "dubium",
    "falso",
    "multo",
    "multum",
    "occulto",
    "paululum",
    "penitus",
    "plurimum",
    "plus",
    "primo",
    "recta",
    "solidum",
    "tacito",
    "tuto"
}