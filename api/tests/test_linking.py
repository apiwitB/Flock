from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from flock_api.linking import Candidate, Observation, decide
from flock_api.topology import Topology

T0 = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)

TOPO = Topology.from_dict(
    {
        "cameras": {
            "G-entry": {"role": "entry"},
            "B1": {"role": "internal"},
            "L2": {"role": "internal"},
            "G-exit": {"role": "exit"},
        },
        "links": [
            {"a": "G-entry", "b": "B1", "min_seconds": 5, "max_seconds": 120},
            {"a": "B1", "b": "L2", "min_seconds": 10, "max_seconds": 180, "both_ways": True},
            {"a": "B1", "b": "G-exit", "min_seconds": 5, "max_seconds": 120},
        ],
    }
)


def obs(camera="B1", after=30, plate=None, color="white", vtype="sedan"):
    return Observation(camera, T0 + timedelta(seconds=after), plate, color, vtype)


def cand(jid=1, plate=None, camera="G-entry", at=0, color="white", vtype="sedan", sim=None):
    return Candidate(jid, plate, camera, T0 + timedelta(seconds=at), color, vtype, sim)


def test_topology_fastest_path_and_direction():
    assert TOPO.fastest("G-entry", "L2") == 15
    assert TOPO.fastest("L2", "B1") == 10  # both_ways
    assert TOPO.fastest("B1", "G-entry") is None  # ทางเข้าวิ่งย้อนไม่ได้
    assert TOPO.is_exit("G-exit") and not TOPO.is_exit("B1")


def test_topology_validation():
    with pytest.raises(ValueError):
        Topology.from_dict({"cameras": {"a": {}}, "links": [{"a": "a", "b": "zz", "min_seconds": 1, "max_seconds": 2}]})
    with pytest.raises(ValueError):
        Topology.from_dict({"cameras": {"a": {}, "b": {}}, "links": [{"a": "a", "b": "b", "min_seconds": 5, "max_seconds": 2}]})
    with pytest.raises(ValueError):
        Topology.from_dict({"cameras": {"a": {"role": "lobby"}}})


def test_example_topology_file_loads():
    path = Path(__file__).resolve().parents[2] / "deploy" / "topology.example.toml"
    if not path.exists():
        pytest.skip("deploy/ is not part of the test image")
    topo = Topology.load(path)
    assert topo.fastest("G-entry", "G-exit") == 10


def test_exact_plate():
    d = decide(obs(plate="1กข1234"), [cand(1, "9ฮฮ9"), cand(2, "1กข1234")], TOPO)
    assert (d.journey_id, d.method, d.score) == (2, "exact", 1.0)


def test_exact_plate_rejected_when_travel_is_impossible():
    # เห็นที่ทางเข้า แล้ว 3 วินาทีต่อมาเห็นป้ายเดียวกันที่ L2 (ต้องใช้อย่างน้อย 15 วินาที) → ไม่ใช่คันเดียวกัน
    d = decide(obs("L2", after=3, plate="1กข1234"), [cand(1, "1กข1234")], TOPO)
    assert d.method == "new"


def test_exact_plate_after_long_parking_is_fine():
    d = decide(obs("G-exit", after=5 * 3600, plate="1กข1234"), [cand(1, "1กข1234", camera="L2")], TOPO)
    assert d.method == "exact"


def test_similar_plate():
    d = decide(obs(plate="1กช1234"), [cand(1, "1กข1234")], TOPO)
    assert (d.journey_id, d.method) == (1, "similar_plate")
    assert d.score == pytest.approx(0.8)


def test_similar_plate_blocked_by_color_conflict():
    d = decide(obs(plate="1กช1234", color="red"), [cand(1, "1กข1234", color="white")], TOPO)
    assert d.method == "new"


def test_similar_plate_tie_is_not_linked():
    d = decide(obs(plate="1กข1234"), [cand(1, "1กช1234"), cand(2, "1กข1284")], TOPO)
    assert d.method == "new" and "equally" in d.reason


def test_two_unrelated_chars_is_not_similar():
    d = decide(obs(plate="1กข1234"), [cand(1, "1งข1294")], TOPO)
    assert d.method == "new"


def test_guess_by_embedding():
    d = decide(obs(), [cand(1, sim=0.91), cand(2, sim=0.70)], TOPO)
    assert (d.journey_id, d.method, d.score) == (1, "guess", 0.91)


def test_guess_needs_threshold_margin_and_adjacency():
    assert decide(obs(), [cand(1, sim=0.79)], TOPO).method == "new"
    assert decide(obs(), [cand(1, sim=0.91), cand(2, sim=0.89)], TOPO).method == "new"
    # ไม่ติดกัน (ทางเข้า → L2 ต้องผ่าน B1)
    assert decide(obs("L2", after=40), [cand(1, sim=0.95)], TOPO).method == "new"
    # ติดกันแต่ช้าเกิน max_seconds (น่าจะจอดไปแล้ว) → ไม่เดา
    assert decide(obs(after=600), [cand(1, sim=0.95)], TOPO).method == "new"
    # เร็วเกิน min_seconds
    assert decide(obs(after=1), [cand(1, sim=0.95)], TOPO).method == "new"


def test_guess_never_joins_conflicting_plates():
    # observation มีป้าย แต่ journey มีป้ายอื่น: embedding คล้ายแค่ไหนก็ไม่ต่อ
    d = decide(obs(plate="1กข1234"), [cand(1, plate="9ฮฮ9", sim=0.99)], TOPO)
    assert d.method == "new"
    # observation มีป้าย journey ไม่มีป้าย: เดาได้
    d = decide(obs(plate="1กข1234"), [cand(1, sim=0.95)], TOPO)
    assert d.method == "guess"


def test_same_camera_short_gap_can_be_guessed():
    d = decide(obs("B1", after=40), [cand(1, camera="B1", at=0, sim=0.9)], TOPO)
    assert d.method == "guess"
    d = decide(obs("B1", after=400), [cand(1, camera="B1", at=0, sim=0.9)], TOPO)
    assert d.method == "new"


def test_unknown_camera_does_not_block_exact_plate_but_blocks_guess():
    assert decide(obs("new-cam", plate="กข1"), [cand(1, "กข1")], TOPO).method == "exact"
    assert decide(obs("new-cam"), [cand(1, sim=0.99)], TOPO).method == "new"


def test_nothing_to_match():
    assert decide(obs(), [], TOPO).method == "new"
