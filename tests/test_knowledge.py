"""Tests for ``src.knowledge`` — the shared project Knowledge Base (layer 2).

Hermetic: every test injects throwaway ``tmp_path`` directories, so nothing
touches ``~/.config/nexus`` and the suite never depends on the seeded docs
(except the one explicit integration check that reads the real ``knowledge/``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.knowledge.base import (
    DEFAULT_LIMIT,
    KnowledgeBase,
    KnowledgeDoc,
    get_knowledge_base,
    normalize_token,
    parse_front_matter,
    reset_knowledge_base,
    tokenize,
)


#────────────────────────────── helpers ──────────────────────────────#


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def kb(tmp_path: Path) -> KnowledgeBase:
    """A base over two empty temp dirs (seed + user)."""
    return KnowledgeBase(tmp_path / "seed", tmp_path / "user")

#────────────────────────────── tokenizing ──────────────────────────────#


def test_normalize_token_strips_diacritics_and_unifies_letters() -> None:
    """Arabic variants collapse to one form: أ/إ/آ→ا, ى→ي, ة→ه, no harakat."""
    assert normalize_token("أَسَاسِيَّة") == "اساسيه"
    assert normalize_token("إلى") == "الي"
    assert normalize_token("Knowledge") == "knowledge"


def test_tokenize_drops_stopwords_and_punctuation() -> None:
    """Stopwords (ar+en) and punctuation vanish; content words survive."""
    tokens = tokenize("The coder must write tests, and من ثم يختبر الكود")
    assert "the" not in tokens
    assert "and" not in tokens
    assert "من" not in tokens
    assert "coder" in tokens
    assert "tests" in tokens
    assert "الكود" in tokens


def test_tokenize_keeps_uppercase_words_whole() -> None:
    """Regression: ``Rules`` must yield ``rules``, not ``ules``."""
    assert tokenize("Rules") == ["rules"]
    assert tokenize("KnowledgeBase") == ["knowledgebase"]


#──────────────────────────── front matter ─────────────────────────────#


def test_parse_front_matter_reads_known_keys_only() -> None:
    """Known keys are read; unknown keys are ignored; the body is returned."""
    meta, body = parse_front_matter(
        "---\ntitle: Hello\nunknown: x\ncategory: core\n---\nBody here\n"
    )
    assert meta == {"title": "Hello", "category": "core"}
    assert body == "Body here\n"


def test_parse_front_matter_without_fence_returns_text_unchanged() -> None:
    """A document with no leading ``---`` is passed through untouched."""
    text = "# Title\ncontent"
    assert parse_front_matter(text) == ({}, text)


def test_parse_front_matter_unterminated_fence_is_not_parsed() -> None:
    """An opening ``---`` with no closing fence stays raw (no metadata)."""
    text = "---\ntitle: Broken\nbody"
    assert parse_front_matter(text) == ({}, text)


def test_parse_front_matter_skips_lines_without_a_colon() -> None:
    """A stray line inside the fence (no ``:``) is ignored, not parsed."""
    meta, body = parse_front_matter("---\ntitle: T\njust a stray line\n---\nX")
    assert meta == {"title": "T"}
    assert body == "X"


#───────────────────────────── documents ──────────────────────────────#


def test_doc_metadata_parsed_from_file(tmp_path: Path) -> None:
    """Title/category/tags/pinned come from front matter; tokens are weighted."""
    seed = tmp_path / "seed"
    _write(
        seed,
        "rules",
        "---\ntitle: Rules\ncategory: core\ntags: a, b\npinned: yes\n---\nbody text",
    )
    doc = KnowledgeBase(tmp_path / "seed", tmp_path / "user").load("rules")
    assert doc is not None
    assert doc.title == "Rules"
    assert doc.category == "core"
    assert doc.tags == ("a", "b")
    assert doc.pinned is True
    assert doc.content == "body text"
    assert "rules" in doc.tokens


def test_doc_title_falls_back_to_heading_then_stem(tmp_path: Path) -> None:
    """No ``title:`` → first heading; plain line → that line; empty → stem."""
    seed = tmp_path / "seed"
    _write(seed, "headed", "# Heading Here\nbody")
    _write(seed, "plain", "just a plain line\nmore")
    _write(seed, "blank", "\n\n# After Blanks\nbody")
    _write(seed, "empty", "")
    base = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    assert base.load("headed").title == "Heading Here"  # type: ignore[union-attr]
    assert base.load("plain").title == "just a plain line"  # type: ignore[union-attr]
    assert base.load("blank").title == "After Blanks"  # type: ignore[union-attr]
    assert base.load("empty").title == "empty"  # type: ignore[union-attr]
    assert base.load("empty").content == ""  # type: ignore[union-attr]


def test_doc_to_dict_is_json_safe(tmp_path: Path) -> None:
    """``to_dict`` exposes size, not the full content."""
    doc = KnowledgeDoc(
        name="n",
        title="t",
        content="secret body",
        path=tmp_path / "n.md",
        category="c",
        tags=("x",),
        pinned=True,
    )
    data = doc.to_dict()
    assert data["name"] == "n"
    assert data["tags"] == ["x"]
    assert data["chars"] == len("secret body")
    assert "content" not in data


#──────────────────────────── the base ────────────────────────────#


def test_list_and_load_and_missing(kb: KnowledgeBase, tmp_path: Path) -> None:
    """Listing is sorted; loading an unknown name yields ``None``."""
    _write(kb.seed_dir, "b", "B body")
    _write(kb.seed_dir, "a", "A body")
    assert kb.list_docs() == ["a", "b"]
    assert len(kb.all_docs()) == 2
    assert kb.load("a") is not None
    assert kb.load("nope") is None


def test_user_override_wins_on_name_collision(tmp_path: Path) -> None:
    """The user dir overrides a seed doc of the same name."""
    seed, user = tmp_path / "seed", tmp_path / "user"
    _write(seed, "shared", "seed version")
    _write(user, "shared", "user version")
    base = KnowledgeBase(seed, user)
    assert base.load("shared").content == "user version"  # type: ignore[union-attr]


def test_refresh_picks_up_a_new_file(tmp_path: Path) -> None:
    """``refresh`` drops the cache so a new file becomes visible."""
    base = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    assert base.list_docs() == []
    _write(base.seed_dir, "late", "late body")
    assert base.list_docs() == []
    base.refresh()
    assert base.list_docs() == ["late"]


def test_missing_source_dirs_are_skipped(tmp_path: Path) -> None:
    """A non-existent seed/user dir does not raise."""
    base = KnowledgeBase(tmp_path / "absent", tmp_path / "also-absent")
    assert base.all_docs() == []


def test_create_false_does_not_mkdir(tmp_path: Path) -> None:
    """``create=False`` leaves the filesystem alone (read-only use)."""
    target = tmp_path / "not-made"
    KnowledgeBase(tmp_path / "seed", target, create=False)
    assert not target.exists()


def test_pinned_docs_are_listed(kb: KnowledgeBase) -> None:
    """Only docs with a truthy ``pinned`` flag are returned."""
    _write(kb.seed_dir, "always", "---\npinned: true\n---\nbody")
    _write(kb.seed_dir, "sometimes", "---\npinned: false\n---\nbody")
    assert [d.name for d in kb.pinned()] == ["always"]


def test_pinned_accepts_arabic_and_english_truthy(kb: KnowledgeBase) -> None:
    """``نعم``/``on``/``1`` all mean pinned."""
    for i, flag in enumerate(("نعم", "on", "1")):
        _write(kb.seed_dir, f"d{i}", f"---\npinned: {flag}\n---\nbody")
    kb.refresh()
    assert len(kb.pinned()) == 3


#───────────────────────────── search ───────────────────────────#


def test_search_ranks_title_over_body(kb: KnowledgeBase) -> None:
    """A title match outranks a body-only match."""
    _write(kb.seed_dir, "titled", "---\ntitle: pytest gates\n---\nnothing else")
    _write(kb.seed_dir, "bodyonly", "---\ntitle: other\n---\npytest appears in body")
    kb.refresh()
    results = kb.search("pytest", limit=5)
    assert [d.name for d in results] == ["titled", "bodyonly"]


def test_search_empty_or_nonpositive_limit_returns_nothing(kb: KnowledgeBase) -> None:
    """An empty query or a non-positive limit yields an empty list."""
    _write(kb.seed_dir, "d", "some body")
    kb.refresh()
    assert kb.search("") == []
    assert kb.search("body", limit=0) == []
    assert kb.search("body", limit=5)[0].name == "d"


def test_search_no_match_returns_empty(kb: KnowledgeBase) -> None:
    """A query with no overlapping tokens returns nothing."""
    _write(kb.seed_dir, "d", "---\ntitle: apples\n---\nfood")
    kb.refresh()
    assert kb.search("transactional postgres") == []


def test_search_is_deterministic_on_ties(kb: KnowledgeBase) -> None:
    """Equal scores break ties by name, so order is stable."""
    _write(kb.seed_dir, "zzz", "---\ntitle: target\n---\n")
    _write(kb.seed_dir, "aaa", "---\ntitle: target\n---\n")
    kb.refresh()
    assert [d.name for d in kb.search("target")] == ["aaa", "zzz"]


#─────────────────────────── selection & render ───────────────────────────#


def test_select_puts_pinned_first_and_dedupes(kb: KnowledgeBase) -> None:
    """Pinned docs lead, and a matching pinned doc is never repeated."""
    _write(kb.seed_dir, "always", "---\ntitle: coder rules\npinned: true\n---\nx")
    _write(kb.seed_dir, "topic", "---\ntitle: coder specifics\n---\ny")
    kb.refresh()
    chosen = kb.select("coder", "coder task", limit=5)
    names = [d.name for d in chosen]
    assert names[0] == "always"
    assert names.count("always") == 1
    assert "topic" in names


def test_select_limit_zero_returns_nothing(kb: KnowledgeBase) -> None:
    """A zero limit disables injection entirely."""
    _write(kb.seed_dir, "always", "---\npinned: true\n---\nx")
    kb.refresh()
    assert kb.select("coder", "task", limit=0) == []


def test_select_respects_limit(kb: KnowledgeBase) -> None:
    """At most ``limit`` docs are returned."""
    for i in range(6):
        _write(kb.seed_dir, f"d{i}", "---\ntitle: coder\n---\nbody")
    kb.refresh()
    assert len(kb.select("coder", "coder", limit=3)) == 3


def test_render_empty_is_empty_string(kb: KnowledgeBase) -> None:
    """Rendering nothing yields ``""`` (a clean no-op injection)."""
    assert kb.render([]) == ""


def test_for_agent_renders_a_usable_block(kb: KnowledgeBase) -> None:
    """The block carries the header, the doc names and the content."""
    _write(kb.seed_dir, "always", "---\ntitle: Always\npinned: true\n---\nPINNED")
    _write(kb.seed_dir, "task", "---\ntitle: Task\n---\nRELEVANT")
    kb.refresh()
    block = kb.for_agent("coder", "a coder task", limit=5)
    assert "قاعدة المعرفة المشتركة" in block
    assert "<!-- docs: always, task -->" in block
    assert "PINNED" in block
    assert "RELEVANT" in block


def test_default_limit_is_four() -> None:
    """The public default limit is a sane small number."""
    assert DEFAULT_LIMIT == 4


#─────────────────────────────── stats ────────────────────────────────#


def test_stats_counts_docs_categories_and_pinned(kb: KnowledgeBase) -> None:
    """Stats reports docs, per-category counts, pinned total and sources."""
    _write(kb.seed_dir, "a", "---\ncategory: core\npinned: true\n---\nbody")
    _write(kb.seed_dir, "b", "---\ncategory: core\n---\nbody")
    _write(kb.seed_dir, "c", "---\ncategory: misc\n---\nbody")
    kb.refresh()
    stats = kb.stats()
    assert stats["docs"] == 3
    assert stats["categories"] == {"core": 2, "misc": 1}
    assert stats["pinned"] == 1
    assert stats["sources"] == [str(kb.seed_dir), str(kb.user_dir)]


#────────────────────────────── singleton ──────────────────────────────#


def test_singleton_is_stable_then_resettable() -> None:
    """``get_knowledge_base`` returns one instance until reset."""
    reset_knowledge_base()
    first = get_knowledge_base()
    assert get_knowledge_base() is first
    reset_knowledge_base()
    assert get_knowledge_base() is not first


#──────────────────── seeded repo knowledge (integration) ────────────────────#


def test_seeded_repo_knowledge_is_present_and_pinned(tmp_path: Path) -> None:
    """The committed ``knowledge/`` carries the shared project facts."""
    from src.knowledge import SEED_DIR

    real = KnowledgeBase(SEED_DIR, tmp_path / "no-user", create=False)
    names = real.list_docs()
    assert {"nexus-core", "gates", "conventions", "training-model"} <= set(names)
    assert len(real.pinned()) >= 3
    block = real.for_agent("coder", "which command verifies the gates?")
    assert "gates" in block


def test_unicode_and_arabic_search_roundtrip(tmp_path: Path) -> None:
    """An Arabic query finds an Arabic doc despite diacritics."""
    seed = tmp_path / "seed"
    _write(seed, "ar", "---\ntitle: بوّابات التحقق\n---\nالأوامر الحقيقية")
    base = KnowledgeBase(seed, tmp_path / "user")
    base.refresh()
    assert [d.name for d in base.search("بوابات التحقق")] == ["ar"]
