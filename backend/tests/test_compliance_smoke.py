"""Smoke tests for the W2-T3 compliance models.

Verifies that :mod:`app.models.compliance` exposes the two expected
SQLAlchemy models (``ComplianceProfile`` and ``ComplianceFinding``) and
that their schema-level invariants hold:

- table names match the W2-T3 contract;
- ``ComplianceFinding.variant_id`` carries an ``ON DELETE CASCADE``
  foreign key to ``story_variants.id`` (resolved by SQLAlchemy via
  string reference so this module stays decoupled from the parallel
  W2-T2 change);
- the combined ``(variant_id, severity)`` index is declared so query
  paths filtering by both columns stay covered;
- each model can be instantiated with the documented required-only
  keyword arguments without raising.

The tests intentionally avoid creating tables in a real engine because
the ``story_variants`` parent table is owned by W2-T2 and is not yet
present in the metadata at the time this smoke test runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.compliance import ComplianceFinding, ComplianceProfile
from app.models.types import ComplianceRegion, ComplianceSeverity


def test_compliance_profile_tablename() -> None:
    """``ComplianceProfile`` must map to the documented table name."""
    assert ComplianceProfile.__tablename__ == "compliance_profiles"


def test_compliance_finding_tablename() -> None:
    """``ComplianceFinding`` must map to the documented table name."""
    assert ComplianceFinding.__tablename__ == "compliance_findings"


def test_compliance_finding_variant_id_foreign_key() -> None:
    """``variant_id`` must be a CASCADE FK to ``story_variants.id``.

    The FK is declared as a string reference so this module does not
    import :class:`StoryVariant` directly; SQLAlchemy resolves the
    target at metadata bind time.
    """
    column = ComplianceFinding.__table__.columns["variant_id"]
    foreign_keys = list(column.foreign_keys)
    assert len(foreign_keys) == 1, "variant_id must declare exactly one FK"

    fk = foreign_keys[0]
    # ``target_fullname`` keeps the original string form, even before
    # the parent table is registered in metadata.
    assert fk.target_fullname == "story_variants.id"
    assert fk.ondelete == "CASCADE"
    assert column.nullable is False
    assert column.index is True


def test_compliance_finding_combined_index_present() -> None:
    """The composite ``(variant_id, severity)`` index must exist.

    Filtering pending findings per variant is the dominant query
    pattern, so this index is part of the W2-T3 contract.
    """
    indexes = {idx.name: idx for idx in ComplianceFinding.__table__.indexes}
    combined = indexes.get("ix_compliance_findings_variant_severity")
    assert combined is not None, "missing combined variant/severity index"

    column_names = [col.name for col in combined.columns]
    assert column_names == ["variant_id", "severity"]


def test_compliance_profile_constructs_with_required_kwargs() -> None:
    """``ComplianceProfile`` must accept its minimal kwarg set.

    ``region`` / ``rules`` / ``is_system`` / ``description`` all carry
    Python-side defaults, so only ``id`` and ``name`` are strictly
    required to construct an instance.
    """
    profile = ComplianceProfile(
        id="cn_mainland_default",
        name="中国大陆 · 默认",
    )

    assert profile.id == "cn_mainland_default"
    assert profile.name == "中国大陆 · 默认"
    # The Python-side default is referenced lazily; verify the column
    # default still resolves to the documented ComplianceRegion enum.
    region_default = ComplianceProfile.__table__.columns["region"].default
    assert region_default is not None
    assert region_default.arg == ComplianceRegion.cn_mainland.value


def test_compliance_finding_constructs_with_required_kwargs() -> None:
    """``ComplianceFinding`` must accept its minimal kwarg set.

    ``severity`` / ``rule_kind`` / ``is_resolved`` rely on column
    defaults, so callers only need to supply the variant linkage,
    rule identification, description, and detection timestamp.
    """
    finding = ComplianceFinding(
        variant_id="variant-1",
        rule_id="banned-1",
        description="禁用词命中",
        detected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert finding.variant_id == "variant-1"
    assert finding.rule_id == "banned-1"
    assert finding.description == "禁用词命中"
    assert finding.detected_at == datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Severity / rule_kind / is_resolved should still come from
    # column-level defaults at INSERT time; verify the schema-side
    # contract instead of the unflushed instance attribute.
    severity_default = ComplianceFinding.__table__.columns["severity"].default
    assert severity_default is not None
    assert severity_default.arg == ComplianceSeverity.warning.value

    rule_kind_default = ComplianceFinding.__table__.columns["rule_kind"].default
    assert rule_kind_default is not None
    assert rule_kind_default.arg == "banned_phrase"

    is_resolved_default = ComplianceFinding.__table__.columns["is_resolved"].default
    assert is_resolved_default is not None
    assert is_resolved_default.arg is False
