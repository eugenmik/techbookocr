from techbookocr.pipeline.postproc.floats import reorder_floats
from techbookocr.pipeline.postproc.items import Item


def _it(i, cat, box, text=""):
    return Item(i, "p", i, cat, text or f"t{i}", bbox=box)


def _order(items):
    return [it.id for it in items]


def test_figure_in_right_column_goes_after_narrow_text_gir_0020R():
    items = [_it(0, "Text", (469, 297, 3148, 436)), _it(1, "Text", (469, 436, 3148, 1610)),
             _it(2, "Text", (469, 1606, 1652, 2333)), _it(3, "Formula", (783, 2371, 1311, 2532)),
             _it(4, "Text", (469, 2574, 1652, 2871)), _it(5, "Formula", (558, 2896, 1548, 3066)),
             _it(6, "Text", (469, 3091, 2509, 3173)), _it(7, "Text", (469, 3168, 3148, 4031)),
             _it(8, "Text", (469, 4027, 3148, 4460)), _it(9, "Text", (469, 4456, 3148, 4609)),
             _it(10, "Picture", (1698, 1217, 3136, 2670)), _it(11, "Caption", (1750, 2716, 3140, 3013))]
    assert reorder_floats(items, {"p": 4984}) == 1
    assert _order(items) == [0, 1, 2, 3, 4, 5, 6, 10, 11, 7, 8, 9]


def test_vor_0180_figures_stay_next_to_their_text():
    items = [_it(2, "Text", (92, 212, 2046, 586)), _it(3, "Text", (92, 591, 1293, 1132)),
             _it(4, "Text", (92, 1137, 1293, 1508)), _it(5, "Picture", (1334, 632, 2043, 1154)),
             _it(6, "Caption", (1398, 1176, 1980, 1268)), _it(7, "Section-header", (151, 1553, 1223, 1728)),
             _it(8, "Section-header", (613, 1781, 757, 1823)), _it(9, "Text", (87, 1848, 1290, 2281)),
             _it(10, "Text", (87, 2284, 1290, 2444)), _it(11, "Text", (87, 2449, 1290, 2662)),
             _it(12, "Picture", (1331, 1305, 2043, 2717)), _it(13, "Caption", (1398, 2739, 1969, 2833))]
    reorder_floats(items, {"p": 2950})
    assert _order(items) == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]  # figure 5 does not move past the text next to figure 12


def test_two_column_page_untouched():
    items = [_it(0, "Text", (100, 100, 950, 1000)), _it(1, "Text", (100, 1000, 950, 2800)),
             _it(2, "Text", (1050, 100, 1900, 900)), _it(3, "Picture", (1050, 950, 1900, 1700)),
             _it(4, "Caption", (1100, 1720, 1850, 1800)), _it(5, "Text", (1050, 1850, 1900, 2800))]
    assert reorder_floats(items, {"p": 3000}) == 0 and _order(items) == [0, 1, 2, 3, 4, 5]


def test_single_column_two_wrapped_figures_keep_their_text():
    items = [_it(0, "Text", (100, 100, 1200, 700)), _it(1, "Picture", (1300, 100, 1900, 650)),
             _it(2, "Caption", (1300, 660, 1900, 700)), _it(3, "Text", (100, 750, 1900, 1500)),
             _it(4, "Text", (100, 1600, 1200, 2300)), _it(5, "Picture", (1300, 1600, 1900, 2200)),
             _it(6, "Caption", (1300, 2210, 1900, 2260)), _it(7, "Text", (100, 2350, 1900, 2800))]
    reorder_floats(items, {"p": 3000})
    assert _order(items) == [0, 1, 2, 3, 4, 5, 6, 7]


def test_table_with_captions_before_the_block_it_overlaps_gir_0345R():
    items = [_it(0, "Text", (427, 310, 3083, 890)), _it(1, "Text", (427, 886, 3083, 2170)),
             _it(2, "Text", (427, 2170, 3083, 2949)), _it(3, "Text", (427, 3221, 3083, 3372)),
             _it(9, "Caption", (2583, 1095, 3083, 1169)), _it(10, "Caption", (1649, 1204, 3021, 1277)),
             _it(11, "Table", (1601, 1300, 3075, 2088))]
    reorder_floats(items, {"p": 4984})
    assert _order(items) == [0, 9, 10, 11, 1, 2, 3]


def test_correct_order_and_plain_pages_untouched():
    items = [_it(0, "Text", (100, 100, 900, 300)), _it(1, "Picture", (100, 320, 900, 600)),
             _it(2, "Caption", (100, 610, 900, 660)), _it(3, "Text", (100, 700, 900, 900))]
    assert reorder_floats(items, {"p": 1400}) == 0 and _order(items) == [0, 1, 2, 3]
    items = [_it(0, "Text", (100, 100, 900, 300)), _it(1, "Text", (100, 320, 900, 600))]
    assert reorder_floats(items, {"p": 1400}) == 0


def test_left_column_figure_and_missing_bbox_untouched():
    # figure on the left, text on the right: not a "side column on the right", so the order is left alone
    items = [_it(0, "Picture", (100, 100, 700, 600)), _it(1, "Text", (800, 100, 1500, 900)),
             _it(2, "Text", (800, 900, 1500, 1200))]
    assert reorder_floats(items, {"p": 1400}) == 0
    items = [Item(0, "p", 0, "Text", "a"), Item(1, "p", 1, "Picture", "", bbox=None)]
    assert reorder_floats(items, {"p": 1400}) == 0
