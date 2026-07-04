def normalize_digraphs(text: str | None) -> str | None:
    """
    Replaces æ/œ ligatures with ae/oe.
    Required by the Pipeline Contract to maintain skeleton identity
    between raw words and macronized words.
    """
    if text is not None:
        if text.isupper():
            return (
                text.replace("æ", "AE")  # Safe fallback
                .replace("œ", "OE")
                .replace("Æ", "AE")
                .replace("Œ", "OE")
            )
        else:
            return (
                text.replace("æ", "ae")
                .replace("œ", "oe")
                .replace("Æ", "Ae")
                .replace("Œ", "Oe")
            )
