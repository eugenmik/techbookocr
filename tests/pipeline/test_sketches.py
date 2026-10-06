import pytest

from techbookocr.config import PipelineConfig
from techbookocr.models.doclayout import Region
from techbookocr.models.errors import TransportError
from techbookocr.models.types import Block
from techbookocr.pipeline.sketches import pick_sketches, reading_order, run_sketches
from techbookocr.pipeline.transport import StageAborted, TransportGuard
from tests.pipeline.fakes import NO_SLEEP, FakeDetector, new_state

CFG = PipelineConfig()
TABLE = Block("Table", "<table><tr><td><img></td><td><img></td></tr></table>", (100, 300, 900, 900))


def test_reading_order_rows_then_columns():
    boxes = [(300, 10, 400, 100), (10, 20, 100, 110), (10, 200, 100, 300), (300, 190, 400, 290)]
    assert reading_order(boxes) == [(10, 20, 100, 110), (300, 10, 400, 100),
                                    (10, 200, 100, 300), (300, 190, 400, 290)]


def test_pick_sketches_filters():
    regions = [Region("image", 0.9, (10, 10, 110, 110)),     # 1% of the area: passes
               Region("image", 0.5, (15, 15, 110, 110)),     # duplicate (IoU > 0.5), less confident
               Region("text", 0.99, (200, 10, 300, 110)),    # not graphics
               Region("chart", 0.2, (400, 10, 500, 110)),    # below the threshold
               Region("figure", 0.8, (0, 0, 1000, 900)),     # 90% of the crop: this is the table itself
               Region("image", 0.8, (600, 10, 620, 30)),     # 0.04%: noise
               Region("chart", 0.7, (10, 500, 110, 600))]
    assert pick_sketches(regions, (1000, 1000), 0.3) == [(10, 10, 110, 110), (10, 500, 110, 600)]


def test_run_sketches_saves_crops_in_page_coords(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", [Block("Text", "Таблица 1", (100, 100, 900, 200)), TABLE,
                           Block("Picture", "", (500, 600, 700, 800))], status="done")
    # table crop with padding 12 is (88, 288, 912, 912); the detector answers in its coordinates
    det = FakeDetector(lambda img: ([Region("image", 0.9, (32, 32, 212, 212))], None))
    assert run_sketches(st, det, tmp_path / "work", tmp_path, CFG, TransportGuard(sleep=NO_SLEEP)) == 1
    assert det.calls == [(824, 624)]
    table, pic = st.blocks("0001")[1:]
    assert [s["bbox"] for s in table.sketches] == [[120, 320, 300, 500], [500, 600, 700, 800]]
    assert [s["path"] for s in table.sketches] == ["images/p0001_tab1_cell1.webp", "images/p0001_tab1_cell2.webp"]
    assert (tmp_path / "images" / "p0001_tab1_cell2.webp").exists()
    assert table.sketches_status == "done" and pic.parent == table.id
    st.close()


def test_detector_content_error(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", [TABLE], status="done")
    run_sketches(st, FakeDetector(lambda img: ([], "boom")), tmp_path / "work", tmp_path, CFG,
                 TransportGuard(sleep=NO_SLEEP))
    b = st.blocks("0001")[0]
    assert b.sketches_status == "failed" and b.sketches_error == "boom" and b.sketches == []
    st.close()


def test_detector_transport_streak_aborts(tmp_path):
    names = ("0001", "0002", "0003", "0004")
    st = new_state(tmp_path, names=names)
    for name in names:
        st.set_layout(name, [TABLE], status="done")
    with pytest.raises(StageAborted) as e:
        run_sketches(st, FakeDetector(lambda img: TransportError("worker died")), tmp_path / "work", tmp_path, CFG,
                     TransportGuard(retries=0, sleep=NO_SLEEP))
    assert len(e.value.items) == 3
    assert st.pending("sketches") == 4  # a transport failure does not mark failed
    assert st.blocks("0001")[0].sketches_error.startswith("transport")
    st.close()


def _drawn(rects, size=(700, 500)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    for r in rects:
        d.rectangle(r, fill="black")
    return im


def test_split_by_ink_gaps_two_by_two():
    from techbookocr.pipeline.sketches import split_by_ink_gaps
    rects = [(50, 50, 250, 150), (350, 50, 650, 150), (50, 300, 250, 450), (350, 300, 650, 450)]
    got = split_by_ink_gaps(_drawn(rects), (20, 20, 680, 480))
    assert sorted(got) == sorted((a, b, c + 1, d + 1) for a, b, c, d in rects)


def test_split_by_ink_gaps_vertical_only_and_single_drawing_untouched():
    from techbookocr.pipeline.sketches import split_by_ink_gaps
    box = (20, 20, 680, 480)
    two_rows = _drawn([(50, 50, 650, 150), (50, 300, 650, 450)])
    assert len(split_by_ink_gaps(two_rows, box)) == 2
    one = _drawn([(50, 50, 650, 450)])
    assert split_by_ink_gaps(one, box) == [box]
    # a narrow gap (under 8% of the side) is one figure, e.g. a dimension line
    narrow = _drawn([(50, 50, 650, 200), (50, 220, 650, 450)])
    assert split_by_ink_gaps(narrow, box) == [box]
    assert split_by_ink_gaps(_drawn([]), box) == [box]  # empty box


def test_split_ignores_specks_as_parts():
    from techbookocr.pipeline.sketches import split_by_ink_gaps
    box = (20, 20, 680, 480)
    im = _drawn([(50, 50, 650, 250), (300, 400, 310, 410)])  # a 10 px speck does not split the box
    assert split_by_ink_gaps(im, box) == [box]


def test_run_sketches_splits_merged_detector_box(tmp_path):
    from techbookocr.pipeline.crops import save_image
    st = new_state(tmp_path, names=("0001",), size=(1000, 1400))
    page = _drawn([(200, 380, 330, 460), (620, 380, 780, 460), (200, 780, 330, 860), (620, 780, 780, 860)],
                  size=(1000, 1400))
    save_image(page, tmp_path / "work" / "pages" / "0001.png")
    st.set_layout("0001", [Block("Table", "<table></table>", (100, 300, 900, 900))], status="done")
    # merged box of all four sketches (crop coordinates with padding 12: (88, 288, ...))
    det = FakeDetector(lambda img: ([Region("image", 0.9, (100, 80, 700, 580))], None))
    run_sketches(st, det, tmp_path / "work", tmp_path, CFG, TransportGuard(sleep=NO_SLEEP))
    boxes = [s["bbox"] for s in st.blocks("0001")[0].sketches]
    assert boxes == [[200, 380, 331, 461], [620, 380, 781, 461], [200, 780, 331, 861], [620, 780, 781, 861]]
    st.close()


def test_run_sketches_does_not_split_narrow_boxes(tmp_path):
    from techbookocr.pipeline.crops import save_image
    st = new_state(tmp_path, names=("0001",), size=(1000, 1400))
    page = _drawn([(200, 380, 330, 460), (200, 780, 330, 860)], size=(1000, 1400))
    save_image(page, tmp_path / "work" / "pages" / "0001.png")
    st.set_layout("0001", [Block("Table", "<table></table>", (100, 300, 900, 900))], status="done")
    det = FakeDetector(lambda img: ([Region("image", 0.9, (100, 80, 300, 580))], None))  # 24% of the crop width
    run_sketches(st, det, tmp_path / "work", tmp_path, CFG, TransportGuard(sleep=NO_SLEEP))
    assert len(st.blocks("0001")[0].sketches) == 1
    st.close()


def test_drop_text_sized():
    from techbookocr.pipeline.sketches import drop_text_sized
    # Voronin p. 265, page 2976 px: cells with "0,3" 38-42 px high are not sketches; a 380 px photo is a sketch
    boxes = [(869, 586, 1032, 624), (1169, 2695, 1238, 2737), (217, 667, 646, 1047)]
    assert drop_text_sized(boxes, 2976) == [(217, 667, 646, 1047)]
