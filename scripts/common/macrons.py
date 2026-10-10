_MACRON_STRIP = str.maketrans('āēīōūȳĀĒĪŌŪȲ', 'aeiouyAEIOUY')


def strip_macrons(text: str) -> str:
    """Return text with macronized vowels replaced by plain vowels."""
    return text.translate(_MACRON_STRIP)
