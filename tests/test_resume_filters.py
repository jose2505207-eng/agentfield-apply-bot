"""
Unit tests for resume_filters.

Pure logic, no LLM, no network. Runs in milliseconds. Cost: $0.

Run with:
  python -m tests.test_resume_filters
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.schemas.resume import ParsedResume, SkillCategory
from src.utils.resume_filters import (
    is_marginal_skill,
    filter_marginal_skills,
    diff_skills,
)


def make_resume(skills: list[SkillCategory]) -> ParsedResume:
    return ParsedResume(
        full_name="Test User",
        email=None,
        phone=None,
        location=None,
        linkedin_url=None,
        github_url=None,
        summary="Test summary.",
        experience=[],
        projects=[],
        education=[],
        skills=skills,
        languages=[],
        awards=[],
    )


def test_is_marginal_skill():
    # Marker must include parentheses to count as marginal
    assert is_marginal_skill("Docker (basics)")
    assert is_marginal_skill("Rust (beginner)")
    assert is_marginal_skill("Kubernetes (learning)")
    assert is_marginal_skill("Vue (self-study)")
    assert is_marginal_skill("Go (familiar)")
    # Case insensitivity
    assert is_marginal_skill("DOCKER (BASICS)")
    # Negative cases
    assert not is_marginal_skill("Python")
    assert not is_marginal_skill("Python (pandas, scikit-learn)")  # context in parens, not marker
    assert not is_marginal_skill("TypeScript")
    # IMPORTANT: a skill that mentions "basics" without parens is NOT marginal.
    # The candidate can put "CI/CD basics" intentionally to mean "I know enough
    # to be useful" but reserve "(basics)" parenthetical for "I'm a beginner".
    # This distinction lets the candidate control the signal.
    assert not is_marginal_skill("CI/CD basics")
    print("  ✓ is_marginal_skill")


def test_filter_removes_marginal_skills():
    r = make_resume([
        SkillCategory(name="Languages", items=["Python", "TypeScript", "Rust (beginner)"]),
        SkillCategory(name="Tools", items=["Git", "Docker (basics)", "CI/CD basics"]),
    ])
    filtered = filter_marginal_skills(r)

    cats = {c.name: c.items for c in filtered.skills}
    assert cats["Languages"] == ["Python", "TypeScript"]
    # "CI/CD basics" stays — no parenthetical marker, so it's not marginal
    assert cats["Tools"] == ["Git", "CI/CD basics"]
    print("  ✓ filter_removes_marginal_skills")


def test_filter_drops_empty_categories():
    r = make_resume([
        SkillCategory(name="Languages", items=["Python"]),
        SkillCategory(name="MarginalsOnly", items=["X (basics)", "Y (learning)"]),
    ])
    filtered = filter_marginal_skills(r)

    category_names = [c.name for c in filtered.skills]
    assert "Languages" in category_names
    assert "MarginalsOnly" not in category_names
    print("  ✓ filter_drops_empty_categories")


def test_filter_preserves_other_fields():
    """The filter must NOT mutate anything other than skills."""
    r = ParsedResume(
        full_name="Jose Ivan",
        email="x@y.com",
        phone=None,
        location="Santa Clara, CA",
        linkedin_url=None,
        github_url="github.com/foo",
        summary="A summary.",
        experience=[],
        projects=[],
        education=[],
        skills=[SkillCategory(name="T", items=["A", "B (basics)"])],
        languages=["English"],
        awards=["An award"],
    )
    filtered = filter_marginal_skills(r)
    assert filtered.full_name == "Jose Ivan"
    assert filtered.email == "x@y.com"
    assert filtered.summary == "A summary."
    assert filtered.languages == ["English"]
    assert filtered.awards == ["An award"]
    print("  ✓ filter_preserves_other_fields")


def test_original_not_mutated():
    """model_copy() must give us isolation."""
    r = make_resume([SkillCategory(name="T", items=["A", "B (basics)"])])
    _ = filter_marginal_skills(r)
    assert r.skills[0].items == ["A", "B (basics)"]
    print("  ✓ original_not_mutated")


def test_diff_skills():
    before = make_resume([
        SkillCategory(name="Languages", items=["Python", "Rust (beginner)"]),
        SkillCategory(name="Tools", items=["Git", "Docker (basics)"]),
    ])
    after = filter_marginal_skills(before)
    dropped = diff_skills(before, after)
    assert "Languages: Rust (beginner)" in dropped
    assert "Tools: Docker (basics)" in dropped
    assert len(dropped) == 2
    print("  ✓ diff_skills")


def test_no_marginals_no_op():
    r = make_resume([
        SkillCategory(name="Languages", items=["Python", "TypeScript"]),
    ])
    filtered = filter_marginal_skills(r)
    assert filtered.skills[0].items == ["Python", "TypeScript"]
    print("  ✓ no_marginals_no_op")


def main():
    print("Running resume_filters unit tests...\n")
    test_is_marginal_skill()
    test_filter_removes_marginal_skills()
    test_filter_drops_empty_categories()
    test_filter_preserves_other_fields()
    test_original_not_mutated()
    test_diff_skills()
    test_no_marginals_no_op()
    print("\n✓ All 7 unit tests passed.")


if __name__ == "__main__":
    main()
