from techbookocr.pipeline.postproc.hyphenation import book_vocabulary, join_hyphens, make_is_word
from techbookocr.pipeline.postproc.spell import DICT_URLS, Speller, ensure_dictionary, spell_stats, speller_langs

AFF = b"SET UTF-8\n"
DIC = "4\nчугун\nсталь\nметалла\nотрицательных\n".encode()


def _fetch(calls):
    def fetch(url):
        calls.append(url)
        return AFF if url.endswith(".aff") else DIC
    return fetch


def test_ensure_dictionary_downloads_once(tmp_path):
    calls = []
    base = ensure_dictionary("ru", tmp_path, _fetch(calls))
    assert base == tmp_path / "ru" and (tmp_path / "ru.aff").exists() and (tmp_path / "ru.dic").exists()
    ensure_dictionary("ru", tmp_path, _fetch(calls))
    assert calls == list(DICT_URLS["ru"])
    assert speller_langs("ru") == ["ru", "en"] and speller_langs("en") == ["en"]


def test_speller_and_stats(tmp_path):
    sp = Speller(["ru"], tmp_path, _fetch([]))
    assert sp.known("чугун") and sp.known("Чугун") and not sp.known("чгун")
    assert sp.known("steel") is None  # no English dictionary
    stats = spell_stats([("0001", "Чугун и сталь, чгун $\\text{чгун}$ ГОСТ steel"), ("0002", "чгун чyгун")], sp)
    assert stats.checked == 5 and stats.unknown == 3 and abs(stats.share - 0.6) < 1e-9
    assert stats.top[0] == ("чгун", 2, ["0001", "0002"]) and ("чyгун", 1, ["0002"]) in stats.top


def test_join_hyphens_vocab():
    vocab = book_vocabulary(["Структура металла и отрицательных значений", "темно серый"])
    is_word = make_is_word(vocab)
    assert join_hyphens("свойства ме-\nталла", is_word) == "свойства металла"
    assert join_hyphens("свойства ста-\nли", is_word) == "свойства ста-\nли"  # "stali" (steel, genitive) is unknown
    assert join_hyphens("отрица-тельных значений", is_word) == "отрицательных значений"
    assert join_hyphens("темно-серый цвет", is_word) == "темно-серый цвет"
    assert join_hyphens("$$ме-\nталла$$", is_word) == "$$ме-\nталла$$"


def test_vocabulary_skips_hyphen_parts():
    v = book_vocabulary(["отрица-тельных и ме-\nталла", "сталь"])
    assert v["отрица"] == 0 and v["тельных"] == 0 and v["ме"] == 0 and v["сталь"] == 1 and v["и"] == 1


def test_inline_hyphen_in_vocab_not_joined():
    """Probe (a): vocab from "tsvet sine-zelyony i metalla" (color blue-green and metal) -> join_hyphens keeps the hyphenated word unchanged."""
    vocab = book_vocabulary(["цвет сине-зелёный и металла"])
    is_word = make_is_word(vocab)
    # Vocabulary should have the hyphenated form (sine-zelyony, "blue-green") but NOT the joined one
    assert is_word("сине-зелёный")
    assert not is_word("синезелёный")
    # When joining, since the hyphenated form is in vocab, don't join
    result = join_hyphens("цвет сине-зелёный цвет", is_word)
    assert result == "цвет сине-зелёный цвет"


def test_inline_hyphen_not_in_vocab_joined():
    """Probe (b): vocab from "otritsatelnykh znacheniy" (negative values) -> the hyphen-split word is joined."""
    vocab = book_vocabulary(["отрицательных значений"])
    is_word = make_is_word(vocab)
    # Vocabulary should have the whole word (otritsatelnykh, "negative") but NOT the hyphenated form
    assert is_word("отрицательных")
    assert not is_word("отрица-тельных")
    # When joining, since hyphenated form is NOT in vocab and joined form IS, join
    result = join_hyphens("отрица-тельных значений", is_word)
    assert result == "отрицательных значений"


def test_soft_hyphen_joined_if_vocab_has_word():
    """Probe (c): vocab from "metalla" (metal) -> the word split as "me-\\r\\ntalla" is joined."""
    vocab = book_vocabulary(["металла"])
    is_word = make_is_word(vocab)
    assert is_word("металла")
    # Soft (line-end) hyphen: join if the joined word is in vocab
    result = join_hyphens("свойства ме-\r\nталла", is_word)
    assert result == "свойства металла"


def test_only_hyphenated_word_not_in_vocab():
    """Probe (d): book_vocabulary of the split word "me-\\ntalla" contains neither "me", "talla" nor "metalla" (Cyrillic)."""
    v = book_vocabulary(["ме-\nталла"])
    # The text only has the soft-hyphenated word with no full form
    # After replacing soft hyphen with space, we have just two short parts of the word (me, talla)
    # They might be in vocab as tiny words, but the point is the whole word (metalla) is not
    assert v["ме"] == 0
    assert v["талла"] == 0
    assert v["металла"] == 0


def test_hyphenated_compound_seen_twice_not_joined():
    """Round 3 Probe (a): vocab from "blue-green and blue-green" (hyphenated word twice) -> stays."""
    vocab = book_vocabulary(["цвет сине-зелёный и сине-зелёный"])
    is_word = make_is_word(vocab)
    # Hyphenated form seen twice (count 2) is a real compound
    assert vocab["сине-зелёный"] == 2
    # When joining with vocab passed, should NOT join because vocab[hyphenated] >= 2
    result = join_hyphens("цвет сине-зелёный цвет", is_word, vocab=vocab)
    assert result == "цвет сине-зелёный цвет"


def test_hyphenated_compound_seen_once_joined_if_word_known():
    """Round 3 Probe (b): book with the split and the whole "negative" -> the split one is joined."""
    vocab = book_vocabulary(["отрица-тельных и отрицательных"])
    is_word = make_is_word(vocab)
    # Vocabulary has both the hyphenated form (count 1) and the whole word
    assert vocab["отрица-тельных"] == 1
    assert vocab["отрицательных"] == 1
    # When joining: joined is known, hyphenated count is 1 < 2, so should join
    result = join_hyphens("текст отрица-тельных значений", is_word, vocab=vocab)
    assert result == "текст отрицательных значений"


def test_joined_form_not_known_not_joined():
    """Round 3 Probe (c): book with hyphenated "blue-green" once, no whole joined form -> stays."""
    vocab = book_vocabulary(["сине-зелёный"])
    is_word = make_is_word(vocab)
    # Vocabulary has the hyphenated form but NOT the joined form
    assert vocab["сине-зелёный"] == 1
    assert not is_word("синезелёный")  # joined form not known
    # When joining: joined is NOT known, so can't join
    result = join_hyphens("цвет сине-зелёный", is_word, vocab=vocab)
    assert result == "цвет сине-зелёный"
