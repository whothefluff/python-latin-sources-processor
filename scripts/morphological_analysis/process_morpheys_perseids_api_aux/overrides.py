# Key: incorrect ref from API, Value: correct ref to use.
DICT_REF_REPLACEMENTS = {
    "meum1": "meum",
    "merito": "merito1",
}

# A set of {form}_{item} keys to completely ignore
FORMS_TO_IGNORE = {
    # It's very likely that future forms of equivalent analyses will have to be added with the next processed works
    "praesepia_1",
    "parum_0",
    "infans_1",
}

IGNORED_DICT_REFS = {
    # These are not found in L&S
    "ne",
    "repperio",
    "penitus3",
    "perpascor",
    "quodam",
    "meum2", # Probably some sort of pronoun, while meum1 refers to the plan (also "wrong", but the reader will find it)
}

# Maps a word to a different word that should be used for the API query
ANALYSIS_ALIASES = {
    # iamque returns an adverb "iamque" that is not found in L&S, so we don't want it
    "iamque": "iam",
    "jamque": "jam",
}

FULL_OVERRIDES = {
    # Not recognized by Morpheus apparently
    "dispersus": (
        [{"form": "dispersus", "item": 0, "dictionaryRef": "dispergo"}],
        [{
            'form': 'dispersus', 'item': 0, 'cnt': 0,
            'partOfSpeech': 'adjective',
            'stem': 'dispers',
            'suffix': 'us',
            'segmentsInfo': 'us, -a, -um', # Inferred by code (replicate behavior)
            'gender': 'masculine',
            'number': 'singular',
            'declension': '1st & 2nd',# Inferred by code (replicate behavior)
            'case': 'nominative',
            'verbForm': 'participle',
            'tense': 'perfect',
            'voice': 'passive',
            'person': None,
        }]
    ),
    # Only recognized by the version of Morpheus with no nice fixes
    "ascribere": (
        [{"form": "ascribere", "item": 0, "dictionaryRef": "ascribo"}],
        [
            {
                'form': 'ascribere', 'item': 0, 'cnt': 0, 'partOfSpeech': 'verb', 'stem': 'a-scrīb', 'suffix': 'ēre',
                'segmentsInfo': '3rd conjugation', 'gender': None, 'number': 'singular', 'declension': None, 'case': None,
                'verbForm': 'indicative', 'tense': 'future', 'voice': 'passive', 'person': '2nd',
            },
            {
                'form': 'ascribere', 'item': 0, 'cnt': 1, 'partOfSpeech': 'verb', 'stem': 'a-scrīb', 'suffix': 'ere',
                'segmentsInfo': '3rd conjugation', 'gender': None, 'number': 'singular', 'declension': None, 'case': None,
                'verbForm': 'imperative', 'tense': 'present', 'voice': 'passive', 'person': '2nd',
            },
            {
                'form': 'ascribere', 'item': 0, 'cnt': 2, 'partOfSpeech': 'verb', 'stem': 'a-scrīb', 'suffix': 'ere',
                'segmentsInfo': '3rd conjugation', 'gender': None, 'number': 'singular', 'declension': None, 'case': None,
                'verbForm': 'indicative', 'tense': 'present', 'voice': 'passive', 'person': '2nd',
            },
            {
                'form': 'ascribere', 'item': 0, 'cnt': 3, 'partOfSpeech': 'noun', 'stem': 'a-scrīb', 'suffix': 'ere',
                'segmentsInfo': None, 'gender': 'neuter', 'number': 'singular', 'declension': None, 'case': None,
                'verbForm': 'infinitive', 'tense': 'present', 'voice': 'active', 'person': None,
            },
        ]
    ),
    "ascribi": (
        [{"form": "ascribi", "item": 0, "dictionaryRef": "ascribo"}],
        [{
            'form': 'ascribi', 'item': 0, 'cnt': 0, 'partOfSpeech': 'noun', 'stem': 'a-scrīb', 'suffix': 'ī',
            'segmentsInfo': None, 'gender': 'neuter', 'number': 'singular', 'declension': None, 'case': None,
            'verbForm': 'infinitive', 'tense': 'present', 'voice': 'passive', 'person': None,
        }]
    ),
    "ascripserunt": (
        [{"form": "ascripserunt", "item": 0, "dictionaryRef": "ascribo"}],
        [{
            'form': 'ascripserunt', 'item': 0, 'cnt': 0, 'partOfSpeech': 'verb', 'stem': 'a-scrīps', 'suffix': 'ērunt',
            'segmentsInfo': 'perfect stem', 'gender': None, 'number': 'plural', 'declension': None, 'case': None,
            'verbForm': 'indicative', 'tense': 'perfect', 'voice': 'active', 'person': '3rd',
        }]
    ),
    "ascriptus": (
        [{"form": "ascriptus", "item": 0, "dictionaryRef": "ascribo"}],
        [{
            'form': 'ascriptus', 'item': 0, 'cnt': 0, 'partOfSpeech': 'adjective', 'stem': 'a-scrīpt', 'suffix': 'us',
            'segmentsInfo': 'us, -a, -um', 'gender': 'masculine', 'number': 'singular', 'declension': '1st & 2nd',
            'case': 'nominative', 'verbForm': 'participle', 'tense': 'perfect', 'voice': 'passive', 'person': None,
        }]
    ),
    # Idem
    "pauper": (
        [{"form": "pauper", "item": 0, "dictionaryRef": "pauper"}],
        [
            {
                'form': 'pauper', 'item': 0, 'cnt': 0, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'er',
                'segmentsInfo': 'er, -eris', 'gender': 'masculine', 'number': 'singular', 'declension': '3rd',
                'case': 'nominative/vocative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauper', 'item': 0, 'cnt': 1, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'er',
                'segmentsInfo': 'er, -eris', 'gender': 'feminine', 'number': 'singular', 'declension': '3rd',
                'case': 'nominative/vocative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
        ]
    ),
    "pauperes": (
        [
            {"form": "pauperes", "item": 0, "dictionaryRef": "pauper"},
            {"form": "pauperes", "item": 1, "dictionaryRef": "paupero"}
        ],
        [
            {
                'form': 'pauperes', 'item': 0, 'cnt': 0, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erēs',
                'segmentsInfo': 'er, -eris', 'gender': 'masculine', 'number': 'plural', 'declension': '3rd',
                'case': 'accusative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperes', 'item': 0, 'cnt': 1, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erēs',
                'segmentsInfo': 'er, -eris', 'gender': 'feminine', 'number': 'plural', 'declension': '3rd',
                'case': 'accusative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperes', 'item': 0, 'cnt': 2, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erēs',
                'segmentsInfo': 'er, -eris', 'gender': 'masculine', 'number': 'plural', 'declension': '3rd',
                'case': 'nominative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperes', 'item': 0, 'cnt': 3, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erēs',
                'segmentsInfo': 'er, -eris', 'gender': 'feminine', 'number': 'plural', 'declension': '3rd',
                'case': 'nominative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperes', 'item': 0, 'cnt': 4, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erēs',
                'segmentsInfo': 'er, -eris', 'gender': 'masculine', 'number': 'plural', 'declension': '3rd',
                'case': 'vocative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperes', 'item': 0, 'cnt': 5, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erēs',
                'segmentsInfo': 'er, -eris', 'gender': 'feminine', 'number': 'plural', 'declension': '3rd',
                'case': 'vocative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperes', 'item': 1, 'cnt': 0, 'partOfSpeech': 'verb', 'stem': 'pauper', 'suffix': 'ēs',
                'segmentsInfo': '1st conjugation', 'gender': None, 'number': 'singular', 'declension': None,
                'case': None, 'verbForm': 'subjunctive', 'tense': 'present', 'voice': 'active', 'person': '2nd',
            },
        ]
    ),
    "pauperi": (
        [{"form": "pauperi", "item": 0, "dictionaryRef": "pauper"}],
        [
            {
                'form': 'pauperi', 'item': 0, 'cnt': 0, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erī',
                'segmentsInfo': 'er, -eris', 'gender': 'masculine', 'number': 'singular', 'declension': '3rd',
                'case': 'dative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperi', 'item': 0, 'cnt': 1, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'erī',
                'segmentsInfo': 'er, -eris', 'gender': 'feminine', 'number': 'singular', 'declension': '3rd',
                'case': 'dative', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
        ]
    ),
    "pauperis": (
        [{"form": "pauperis", "item": 0, "dictionaryRef": "pauper"}],
        [
            {
                'form': 'pauperis', 'item': 0, 'cnt': 0, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'eris',
                'segmentsInfo': 'er, -eris', 'gender': 'masculine', 'number': 'singular', 'declension': '3rd',
                'case': 'genitive', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
            {
                'form': 'pauperis', 'item': 0, 'cnt': 1, 'partOfSpeech': 'noun', 'stem': 'paup', 'suffix': 'eris',
                'segmentsInfo': 'er, -eris', 'gender': 'feminine', 'number': 'singular', 'declension': '3rd',
                'case': 'genitive', 'verbForm': None, 'tense': None, 'voice': None, 'person': None,
            },
        ]
    ),
}

FORMS = {
    "fas_0_0": {
        "partOfSpeech": "noun",
        "gender": "neuter",
        "number": "singular",
        "case": "nominative/accusative",
    },
    "nil_0_0": {
        "partOfSpeech": "noun",
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
    "os_0_0": {
         "number": "singular",
    },
    "os_0_1": {
        "number": "singular",
    },
    "os_0_2": {
        "number": "singular",
    },
    "satis_1_1": {
        "partOfSpeech": "adjective",
        "gender": None,
    },
    "nihil_0_1": {
        "case": "nominative/accusative",
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
