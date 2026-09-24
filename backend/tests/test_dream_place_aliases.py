from app.services.dream_place_aliases import source_place_aliases


def test_only_caption_attached_local_names_are_aliases():
    caption = "Dinosaur Spine ridge (Sống Lưng Khủng Long). Dolphin Rock (Mỏm Cá Heo). Windy Peak (Đỉnh Gió). Lonely Tree (Cây Cô Đơn)."
    assert source_place_aliases("Dinosaur Spine ridge", caption) == ["Sống Lưng Khủng Long"]
    assert source_place_aliases("Dolphin Rock", caption) == ["Mỏm Cá Heo"]
    assert source_place_aliases("Windy Peak", caption) == ["Đỉnh Gió"]
    assert source_place_aliases("Lonely Tree", caption) == ["Cây Cô Đơn"]
    assert source_place_aliases("Other ridge", caption) == []


def test_aliases_are_bounded_case_accent_normalized_and_keep_original_spelling():
    caption = "CAFÉ BLUE (Café Azul). Cafe Blue (CAFE AZUL). Cafe Blue (Café Bleu). Cafe Blue (Blue Kafe)."
    assert source_place_aliases("Cafe Blue", caption) == ["Café Azul", "Café Bleu"]
    assert source_place_aliases("Cafe Blue", "NotCafe Blue (Unrelated Place)") == []


def test_annotations_instructions_urls_and_guessed_translations_are_not_aliases():
    for annotation in ["free entrance", "closed Monday", "near the square", "formerly Garden Cafe", "book now", "12 minutes", "https://evil.invalid", "click this link", "A full sentence."]:
        assert source_place_aliases("Cafe Blue", f"Cafe Blue ({annotation})") == []
    assert source_place_aliases("Cafe Blue", "The local name may be Cafe Azul") == []
    assert source_place_aliases(None, "Cafe Blue (Café Azul)") == []
