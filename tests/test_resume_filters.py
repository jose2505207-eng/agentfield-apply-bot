"""
Unit tests for resume_filters.

Pure logic, no LLM, no network. Cost: $0.

Run with:
  python -m tests.test_resume_filters
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.schemas.resume import ParsedResume, SkillCategory
from src.schemas.job import ScoreResult
from src.utils.resume_filters import (
    is_marginal_skill,
    filter_marginal_skills,
    filter_marginal_from_score,
    diff_skills,
)


def make_resume(skills: list[SkillCategory]) -> ParsedResume:
    return ParsedResume(
        full_name="Test User",
        email=None, phone=None, location=None,
        linkedin_url=None, github_url=None,
        summary="Test summary.",
        experience=[], projects=[], education=[],
        skills=skills,
        languages=[], awards=[],
    )


def make_score(**kwargs) -> ScoreResult:
    """Helper to build a ScoreResult with defaults."""
    return ScoreResult(
        score=kwargs.get("score", 75),
        verdict=kwargs.get("verdict", "apply"),
        reasoning=kwargs.get("reasoning", "Good fit."),
        matching_skills=kwargs.get("matching_skills", []),
        missing_skills=kwargs.get("missing_skills", []),
        strengths=kwargs.get("strengths", []),
        concerns=kwargs.get("concerns", []),
    )


def test_is_marginal_skill():
    assert is_marginal_skill("Docker (basics)")
    assert is_marginal_skill("Rust (beginner)")
    assert is_marginal_skill("Kubernetes (learning)")
    assert is_marginal_skill("DOCKER (BASICS)")
    assert not is_marginal_skill("Python")
    assert not is_marginal_skill("Python (pandas, scikit-learn)")
    assert not is_marginal_skill("CI/CD basics")  # no parens, not marginal
    print("  ✓ is_marginal_skill")


def test_filter_removes_marginal_skills():
    r = make_resume([
        SkillCategory(name="Languages", items=["Python", "Rust (beginner)"]),
        SkillCategory(name="Tools", items=["Git", "Docker (basics)", "CI/CD basics"]),
    ])
    filtered = filter_marginal_skills(r)
    cats = {c.name: c.items for c in filtered.skills}
    assert cats["Languages"] == ["Python"]
    assert cats["Tools"] == ["Git", "CI/CD basics"]
    print("  ✓ filter_removes_marginal_skills")


def test_filter_drops_empty_categories():
    r = make_resume([
        SkillCategory(name="Languages", items=["Python"]),
        SkillCategory(name="MarginalsOnly", items=["X (basics)", "Y (learning)"]),
    ])
    filtered = filter_marginal_skills(r)
    names = [c.name for c in filtered.skills]
    assert "Languages" in names
    assert "MarginalsOnly" not in names
    print("  ✓ filter_drops_empty_categories")


def test_filter_preserves_other_fields():
    r = ParsedResume(
        full_name="Jose Ivan", email="x@y.com", phone=None, location="SC, CA",
        linkedin_url=None, github_url="github.com/foo",
        summary="A summary.", experience=[], projects=[], education=[],
        skills=[SkillCategory(name="T", items=["A", "B (basics)"])],
        languages=["English"], awards=["An award"],
    )
    f = filter_marginal_skills(r)
    assert f.full_name == "Jose Ivan"
    assert f.email == "x@y.com"
    assert f.awards == ["An award"]
    print("  ✓ filter_preserves_other_fields")


def test_original_not_mutated():
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


# === Tests for the new ScoreResult filter ===

def test_score_filter_removes_marginal_from_matching_skills():
    """Docker mentioned in matching_skills should be stripped if marginal in resume."""
    resume = make_resume([
        SkillCategory(name="Tools", items=["Git", "Docker (basics)"]),
    ])
    score = make_score(matching_skills=["Python", "Docker", "Git"])
    filtered = filter_marginal_from_score(score, resume)
    assert "Docker" not in filtered.matching_skills
    assert "Python" in filtered.matching_skills
    assert "Git" in filtered.matching_skills
    print("  ✓ score_filter_removes_marginal_from_matching_skills")


def test_score_filter_removes_marginal_from_strengths():
    resume = make_resume([
        SkillCategory(name="Tools", items=["Docker (basics)"]),
    ])
    score = make_score(strengths=[
        "Strong Python background",
        "Experience with Docker for containerization",
    ])
    filtered = filter_marginal_from_score(score, resume)
    assert len(filtered.strengths) == 1
    assert "Python" in filtered.strengths[0]
    print("  ✓ score_filter_removes_marginal_from_strengths")


def test_score_filter_scrubs_reasoning_text():
    """Sentences mentioning marginal skills should be removed from reasoning."""
    resume = make_resume([
        SkillCategory(name="Tools", items=["Docker (basics)"]),
    ])
    score = make_score(
        reasoning="The candidate is strong in Python. Docker experience aligns with deployment needs. Bilingual is a plus."
    )
    filtered = filter_marginal_from_score(score, resume)
    assert "docker" not in filtered.reasoning.lower()
    assert "Python" in filtered.reasoning
    assert "Bilingual" in filtered.reasoning
    print("  ✓ score_filter_scrubs_reasoning_text")


def test_score_filter_noop_when_no_marginals():
    """If no marginal skills in resume, the score passes through unchanged."""
    resume = make_resume([
        SkillCategory(name="Languages", items=["Python", "Rust"]),
    ])
    score = make_score(
        matching_skills=["Python", "Docker"],
        reasoning="Strong with Python and Docker.",
    )
    filtered = filter_marginal_from_score(score, resume)
    assert filtered.matching_skills == ["Python", "Docker"]
    assert filtered.reasoning == "Strong with Python and Docker."
    print("  ✓ score_filter_noop_when_no_marginals")


def main():
    print("Running resume_filters unit tests...\n")
    test_is_marginal_skill()
    test_filter_removes_marginal_skills()
    test_filter_drops_empty_categories()
    test_filter_preserves_other_fields()
    test_original_not_mutated()
    test_diff_skills()
    test_no_marginals_no_op()
    test_score_filter_removes_marginal_from_matching_skills()
    test_score_filter_removes_marginal_from_strengths()
    test_score_filter_scrubs_reasoning_text()
    test_score_filter_noop_when_no_marginals()
    print("\n✓ All 11 unit tests passed.")


if __name__ == "__main__":
    main()
