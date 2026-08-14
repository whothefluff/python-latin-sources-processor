def apply_contract_casing(word_form: str, is_proper_noun: bool) -> str:
    """
    Enforces the 'Match Domain Casing Rule' for dictionary joins.
    - Proper nouns -> Capitalized (Title Case)
    - Common nouns/Other -> lowercase
    """
    if not word_form:
        return word_form
    if is_proper_noun:
        return word_form.capitalize()
    return word_form.lower()