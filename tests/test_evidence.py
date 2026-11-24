from indubio.evidence.models import EpistemicLayer, EvidenceRecord, visible_records


def test_hidden_truth_cannot_be_disclosed_even_if_acl_lists_actor():
    records = [
        EvidenceRecord(
            evidence_id="secret", summary="True fact", layer=EpistemicLayer.HIDDEN_TRUTH,
            visible_to_actor_ids={"judge"}
        ),
        EvidenceRecord(
            evidence_id="exhibit", summary="Disclosed exhibit", layer=EpistemicLayer.DISCLOSED,
            visible_to_actor_ids={"judge"}
        ),
    ]
    assert [x.evidence_id for x in visible_records(records, "judge")] == ["exhibit"]
    assert visible_records(records, "defense") == []
