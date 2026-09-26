"""ha_ws.py 테스트. 실행: uvx pytest -q -p no:cacheprovider scripts/test_ha_ws.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ha_ws


def test_device_view_matches_either_name_and_collects_entities() -> None:
    devices = [
        {
            "id": "d1",
            "name": "Outside Temperature",
            "name_by_user": None,
            "area_id": None,
        },
        {
            "id": "d2",
            "name": "Bed Light",
            "name_by_user": "outside temperature",
            "area_id": "a",
        },
        {"id": "d3", "name": "Other", "name_by_user": None, "area_id": None},
    ]
    entities = [
        {"entity_id": "sensor.outside_temperature", "device_id": "d1", "name": None},
        {"entity_id": "light.bed_light", "device_id": "d2"},
        {"entity_id": "sensor.other", "device_id": "d3"},
    ]
    view = ha_ws.device_view(devices, entities, "OUTSIDE temperature")
    assert [d["id"] for d in view] == ["d1", "d2"]
    assert [e["entity_id"] for e in view[0]["entities"]] == [
        "sensor.outside_temperature"
    ]


def test_kubectl_argv_quotes_only_appended_args() -> None:
    assert ha_ws.kubectl_argv(
        "ssh cp kubectl", ["exec", "-i", "deploy/x", "--", "env", "A=b c"]
    ) == [
        "ssh",
        "cp",
        "kubectl exec -i deploy/x -- env 'A=b c'",
    ]
