from typing import Dict, FrozenSet, Iterable, Mapping, NamedTuple

# Key: incorrect ref from API, Value: correct ref to use.
DICT_REF_REPLACEMENTS = {
}

# Headwords whose analyses are ignored: for the words given, or for every word when none are
IGNORED_DICT_REFS: Dict[str, FrozenSet[str]] = {
}

# Maps a word to a different word that should be used for the API query
ANALYSIS_ALIASES = {
}

#: Detached enclitics: the ne of tune is -ne, apart from the word ne
DETACHED_ENCLITICS = {
    "-que": (
        [{"form": "-que", "item": 0, "dictionaryRef": "que"}],
        [{"form": "-que", "item": 0, "cnt": 0, "partOfSpeech": "conjunction", "stem": "que"}],
    ),
    "-ne": (
        [{"form": "-ne", "item": 0, "dictionaryRef": "ne2"}],
        [{"form": "-ne", "item": 0, "cnt": 0, "partOfSpeech": "adverb", "stem": "ne"}],
    ),
    "-ve": (
        [{"form": "-ve", "item": 0, "dictionaryRef": "ve1"}],
        [{"form": "-ve", "item": 0, "cnt": 0, "partOfSpeech": "conjunction", "stem": "ve"}],
    ),
    "-dum": (
        [{"form": "-dum", "item": 0, "dictionaryRef": "dum"}],
        [{"form": "-dum", "item": 0, "cnt": 0, "partOfSpeech": "adverb", "stem": "dum"}],
    ),
}

FULL_OVERRIDES = {
    **DETACHED_ENCLITICS,
}


class ReadingRule(NamedTuple):
    """A fix for the inflections of Morpheus's answers that have every value in match."""
    headword: str  # as dictionaryRef has it
    match: Mapping[str, str]  # the inflection's elements, as Morpheus names them
    changes: Mapping[str, object] | None  # output fields, a list giving one inflection per value; None drops it
    words: FrozenSet[str] = frozenset()  # the words it's for; none: every word with the reading


# The elements of Morpheus's inflections that a rule can match, and the output fields that it can change
MATCHABLE_ELEMENTS = frozenset({"pofs", "decl", "case", "gend", "num", "mood", "pers", "tense", "voice", "comp",
                                "stemtype", "derivtype", "morph", "dial"})
CHANGEABLE_FIELDS = frozenset({"partOfSpeech", "segmentsInfo", "gender", "number", "declension", "case", "verbForm",
                               "tense", "voice", "person"})


def check_rules(rules: Iterable[ReadingRule]):
    """Raises when a rule matches an element that Morpheus doesn't give, changes a field that the output doesn't have,
    or changes no field."""
    for rule in rules:
        unknown = sorted(set(rule.match) - MATCHABLE_ELEMENTS) + sorted(set(rule.changes or {}) - CHANGEABLE_FIELDS)
        if unknown:
            raise ValueError(f"{rule} has elements or fields that no inflection has: {unknown}")
        if rule.changes is not None and not rule.changes:
            raise ValueError(f"{rule} changes no field; a rule that drops a reading has changes None")


FORMS = (
    # Morpheus gives fas, a neuter noun in L&S, no part of speech, gender, number or case
    ReadingRule(headword="fas", match={"stemtype": "indecl"},
                changes={"partOfSpeech": "noun", "gender": "neuter", "number": "singular",
                         "case": ["nominative", "accusative"]},
                words=frozenset({"fas"})),
    # Morpheus gives eunti and circumeunti, datives of present participles, no gender
    ReadingRule(headword="circumeo", match={"mood": "participle", "tense": "present"},
                changes={"gender": ["masculine", "feminine", "neuter"]}, words=frozenset({"circumeunti"})),
    ReadingRule(headword="eo1", match={"mood": "participle", "tense": "present"},
                changes={"gender": ["masculine", "feminine", "neuter"]}, words=frozenset({"eunti"})),
    # Morpheus gives altiore, an ablative comparative, no gender
    ReadingRule(headword="alo", match={"stemtype": "pp4", "comp": "comparative"},
                changes={"gender": ["masculine", "feminine", "neuter"]}, words=frozenset({"altiore"})),
    ReadingRule(headword="altus1", match={"comp": "comparative"},
                changes={"gender": ["masculine", "feminine", "neuter"]}, words=frozenset({"altiore"})),
    # Morpheus gives the adjective plus no gender, and in the singular it's neuter
    ReadingRule(headword="multus", match={"stemtype": "irreg_adj3"}, changes={"gender": "neuter"},
                words=frozenset({"plus"})),
    # Morpheus gives the indeclinable satis as a neuter, which would be a noun; L&S has an adjective without gender
    ReadingRule(headword="satis", match={"stemtype": "indecl"}, changes={"partOfSpeech": "adjective", "gender": None}),
    # Morpheus's stem type for celer, celeris, celere gives no segments
    ReadingRule(headword="celer1", match={"stemtype": "0_adj3"}, changes={"segmentsInfo": ", -is, -e"},
                words=frozenset({"celeri"})),
)
check_rules(FORMS)

# Whitelist (many errors in morpheus with fake adverbs)
TRUE_ADVERB_FORMS = {
    "brevi",
    "dubium",
    "falso",
    "insueta",
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