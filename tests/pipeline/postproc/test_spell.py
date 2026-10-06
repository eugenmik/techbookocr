

def test_word_stats_split_on_markup():
    from techbookocr.pipeline.postproc.hyphenation import book_vocabulary
    v = book_vocabulary(["Способы ликвидации<br>Снижение влаги"])
    assert v["ликвидации"] == 1 and v["снижение"] == 1 and v["ликвидацииснижение"] == 0
