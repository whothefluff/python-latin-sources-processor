import os
from typing import Dict

from scripts.library.process_work import WorkConfiguration, publish_work
from scripts.library.util.proper_noun import ProperNounState
from scripts.library.util.spelling import LetterConvention
from scripts.library.util.token_classification import TokenType

LETTER_CONVENTION = LetterConvention(uv_lowercase="uv", uv_capitals="UV", ij_lowercase="i", ij_capitals="I")

WORK_SPECIFIC_TOKEN_OVERRIDES: Dict[int, TokenType] = {
    # e.g. "I" used as the numeral 1, not "ire"
    # 107: TokenType.NUMERAL,
}

WORK_SPECIFIC_EXPANSIONS: Dict[int, str] = {
    # 42: "Gāiō", # "C." used in a dative context at fragment 42
    # 107: "ūnum", # "I" used as an accusative numeral at fragment 107
}

# An override is for a word whose printed case looks it up wrong: tartareo, the adjective Tartareus printed lowercase,
# which L&S and Morpheus have only capitalized.
# A personification (Sol, Religio, Dolus) needs none: a capital inside a sentence on a common word makes it either,
# which finds the common word and keeps the capital
WORK_SPECIFIC_PROPER_NOUN_OVERRIDES: Dict[int, ProperNounState | None] = {
    7626: ProperNounState.YES, # 'tartareo' for 'Tartareo': the adjective Tartareus, which this edition prints lowercase for some reason
    13903: ProperNounState.NO, # Terraneola is not found in L&S, but it's just from terra + -olus
    13916: ProperNounState.NO, # terraneolam is not found in L&S, but it's just from terra + -olus
}


def asset_path(asset_name):
    file_path = os.path.join(project_root( ), "data", "library", "item", "phaedrus", asset_name)
    return file_path


def project_root( ):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname( os.path.dirname( os.path.dirname( script_dir ) ) )
    return root


# noinspection SpellCheckingInspection
PHAEDRUS = WorkConfiguration(
    edition_urn='urn:cts:latinLit:phi0975.phi001.perseus-lat2',
    cited_division_subtypes=('book', 'poem'),
    poem_types_by_n={'prologus': 'PROL', 'epilogus': 'EPIL'},
    letter_convention=LETTER_CONVENTION,
    token_overrides=WORK_SPECIFIC_TOKEN_OVERRIDES,
    expansions=WORK_SPECIFIC_EXPANSIONS,
    proper_noun_overrides=WORK_SPECIFIC_PROPER_NOUN_OVERRIDES,
    author_abbreviations=('Phaedr.', 'Phaed.'),
    work_about_file=asset_path('about_phi0975_phi001.txt'),
    author_about_file=asset_path('about.txt'),
    author_image_file=asset_path('expanded.webp'),
)


if __name__ == "__main__":
    # noinspection HttpUrlsUsage
    xml_file = asset_path("phi0975.phi001.perseus-lat2_modified.xml")
    output_dir_outer = project_root( ) + '/output/library/item/phaedrus/'
    with open(xml_file, 'r', encoding='utf-8') as file:
        xml_string_outer = file.read()  # Parse the XML file as a string
    publish_work(xml_string_outer, output_dir_outer, PHAEDRUS)
    print(f"Data has been successfully exported to CSV files in {output_dir_outer}.")
