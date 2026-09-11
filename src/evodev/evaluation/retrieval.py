"""为经验检索计算可解释的相关性分数。"""

from collections.abc import Iterable

from evodev.domain.experiences import Experience, ExperienceMatch

MINIMUM_MATCH_SCORE = 2.5

TAG_WEIGHTS = {
    "error": 4.0,
    "file": 3.5,
    "function": 3.0,
    "tech": 2.0,
    "term": 2.5,
    "task": 0.25,
    "ext": 0.25,
}

TAG_LABELS = {
    "error": "错误类型",
    "file": "文件名",
    "function": "函数名",
    "tech": "技术特征",
    "term": "任务关键词",
    "task": "任务类型",
    "ext": "文件扩展名",
}


def score_experience_match(
    experience: Experience,
    query_tags: Iterable[str],
) -> ExperienceMatch | None:
    """综合标签相关性和历史质量计算匹配结果。"""
    matched_tags = sorted(set(experience.tags).intersection(query_tags))
    if not matched_tags:
        return None

    relevance_score = sum(_tag_weight(tag) for tag in matched_tags)
    quality_factor = 0.5 + experience.quality_score
    score = relevance_score * quality_factor
    if score < MINIMUM_MATCH_SCORE:
        return None

    return ExperienceMatch(
        experience=experience,
        score=score,
        relevance_score=relevance_score,
        quality_factor=quality_factor,
        matched_tags=matched_tags,
        reasons=[_tag_reason(tag) for tag in matched_tags],
    )


def rank_experience_matches(
    experiences: Iterable[Experience],
    query_tags: Iterable[str],
    *,
    limit: int = 3,
) -> list[ExperienceMatch]:
    """过滤低分结果，并按最终分数与历史质量稳定排序。"""
    if limit < 1:
        return []
    tags = list(query_tags)
    matches = [
        match
        for experience in experiences
        if (match := score_experience_match(experience, tags)) is not None
    ]
    matches.sort(
        key=lambda match: (
            match.score,
            match.relevance_score,
            match.experience.quality_score,
            match.experience.usage_count,
            match.experience.created_at,
        ),
        reverse=True,
    )
    return matches[:limit]


def _tag_weight(tag: str) -> float:
    category, _, _ = tag.partition(":")
    return TAG_WEIGHTS.get(category, 1.0)


def _tag_reason(tag: str) -> str:
    category, _, value = tag.partition(":")
    label = TAG_LABELS.get(category, "检索特征")
    return f"{label}匹配：{value}"
